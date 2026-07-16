"""
Matching engine (FUNCTION 4).

For every recall/alert record, the engine looks for the single best
corresponding hospital inventory item using a priority cascade - the
first tier that produces a confident hit wins; lower tiers only run when
higher ones don't:

    1. UDI                  - exact match (case/space-insensitive)
    2. Model Number         - exact match
    3. Catalog Number       - exact match
    4. Manufacturer         - exact match, combined with product-name
                              similarity (manufacturer alone is too weak
                              a signal to call a match by itself)
    5. Product Name         - fuzzy similarity (RapidFuzz) against device name
    6. Fuzzy Matching       - weighted fuzzy similarity across manufacturer
                              + product + model combined, as a last resort

The best-scoring inventory item overall is kept per recall/alert and
classified as Matched / Possible Match / Not Matched using two
user-configurable thresholds (`fuzzy_threshold` for Matched,
`possible_threshold` for Possible Match).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional, Protocol

from rapidfuzz import fuzz

from app.models.enums import MatchMethod, MatchStatus, RecallSource
from app.models.inventory import InventoryItem
from app.models.match import MatchResult


class _RecallLike(Protocol):
    recall_number: str
    manufacturer: str
    model_number: str
    catalog_number: str


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _recall_product_name(recall) -> str:
    return getattr(recall, "product", None) or getattr(recall, "title", None) or ""


def _recall_identifier(recall) -> str:
    """FDA recalls key off `recall_number`; ECRI alerts key off `alert_number`."""
    return getattr(recall, "recall_number", None) or getattr(recall, "alert_number", None) or ""


def _recall_udi(recall) -> str:
    return getattr(recall, "udi", "") or ""


@dataclass
class _Candidate:
    item: InventoryItem
    score: float
    method: MatchMethod
    reason: str


def _score_candidate(recall, item: InventoryItem) -> _Candidate:
    recall_udi = _norm(_recall_udi(recall))
    recall_model = _norm(getattr(recall, "model_number", ""))
    recall_catalog = _norm(getattr(recall, "catalog_number", ""))
    recall_manufacturer = _norm(getattr(recall, "manufacturer", ""))
    recall_product = _recall_product_name(recall)

    # Priority 1: UDI exact match.
    if recall_udi and _norm(item.udi) and recall_udi == _norm(item.udi):
        return _Candidate(item, 100.0, MatchMethod.UDI, "Exact UDI match")

    # Priority 2: Model number exact match.
    if recall_model and _norm(item.model_number) and recall_model == _norm(item.model_number):
        return _Candidate(item, 98.0, MatchMethod.MODEL_NUMBER, "Exact model number match")

    # Priority 3: Catalog number exact match.
    if recall_catalog and _norm(item.catalog_number) and recall_catalog == _norm(item.catalog_number):
        return _Candidate(item, 95.0, MatchMethod.CATALOG_NUMBER, "Exact catalog number match")

    # Priority 4: Manufacturer exact match + product name similarity.
    manufacturer_hit = bool(recall_manufacturer) and recall_manufacturer == _norm(item.manufacturer)
    product_similarity = (
        fuzz.token_sort_ratio(recall_product, item.device_name)
        if recall_product and item.device_name
        else 0.0
    )
    if manufacturer_hit and product_similarity >= 60:
        score = 80.0 + min(product_similarity, 100) * 0.15  # 80-95 range
        return _Candidate(
            item,
            score,
            MatchMethod.MANUFACTURER,
            f"Manufacturer matched exactly; product name similarity {product_similarity:.0f}%",
        )

    # Priority 5: Product name fuzzy match alone.
    if product_similarity >= 60:
        return _Candidate(
            item,
            product_similarity,
            MatchMethod.PRODUCT_NAME,
            f"Product name similarity {product_similarity:.0f}%",
        )

    # Priority 6: last-resort weighted fuzzy match across combined fields.
    recall_blob = " ".join(
        filter(None, [getattr(recall, "manufacturer", ""), recall_product, getattr(recall, "model_number", "")])
    )
    item_blob = " ".join(filter(None, [item.manufacturer, item.device_name, item.model_number, item.brand]))
    fuzzy_score = fuzz.WRatio(recall_blob, item_blob) if recall_blob and item_blob else 0.0
    return _Candidate(item, fuzzy_score, MatchMethod.FUZZY, f"Overall fuzzy similarity {fuzzy_score:.0f}%")


def _classify(score: float, matched_threshold: float, possible_threshold: float) -> MatchStatus:
    if score >= matched_threshold:
        return MatchStatus.MATCHED
    if score >= possible_threshold:
        return MatchStatus.POSSIBLE_MATCH
    return MatchStatus.NOT_MATCHED


class MatchingService:
    def __init__(self, matched_threshold: float = 90.0, possible_threshold: float = 75.0):
        self.matched_threshold = matched_threshold
        self.possible_threshold = possible_threshold

    def match_one(
        self,
        recall,
        source: RecallSource,
        inventory_items: list[InventoryItem],
        report_period: Optional[tuple[date, date]] = None,
    ) -> MatchResult:
        """Return the single best MatchResult for one recall against the full inventory."""
        best: Optional[_Candidate] = None
        for item in inventory_items:
            candidate = _score_candidate(recall, item)
            if best is None or candidate.score > best.score:
                best = candidate

        if best is None:
            return MatchResult(
                recall_source=source,
                recall_number=_recall_identifier(recall),
                hospital_asset_number="",
                manufacturer=getattr(recall, "manufacturer", ""),
                model="",
                confidence_score=0.0,
                status=MatchStatus.NOT_MATCHED,
                method=MatchMethod.NONE,
                reason="No inventory items to compare against.",
                recall_id=getattr(recall, "id", None),
                report_period_start=report_period[0] if report_period else None,
                report_period_end=report_period[1] if report_period else None,
            )

        status = _classify(best.score, self.matched_threshold, self.possible_threshold)
        return MatchResult(
            recall_source=source,
            recall_number=_recall_identifier(recall),
            hospital_asset_number=best.item.asset_number if status != MatchStatus.NOT_MATCHED else "",
            manufacturer=getattr(recall, "manufacturer", ""),
            model=getattr(recall, "model_number", "") or best.item.model_number,
            confidence_score=round(best.score, 1),
            status=status,
            method=best.method if status != MatchStatus.NOT_MATCHED else MatchMethod.NONE,
            reason=best.reason,
            recall_id=getattr(recall, "id", None),
            inventory_id=best.item.id if status != MatchStatus.NOT_MATCHED else None,
            report_period_start=report_period[0] if report_period else None,
            report_period_end=report_period[1] if report_period else None,
        )

    def match_all(
        self,
        fda_recalls: list,
        ecri_alerts: list,
        inventory_items: list[InventoryItem],
        report_period: Optional[tuple[date, date]] = None,
    ) -> list[MatchResult]:
        results = [
            self.match_one(r, RecallSource.FDA, inventory_items, report_period) for r in fda_recalls
        ]
        results += [
            self.match_one(a, RecallSource.ECRI, inventory_items, report_period) for a in ecri_alerts
        ]
        return results
