from dataclasses import dataclass, field
from typing import Any

from app.models.enums import MatchMethod, MatchStatus, RecallSource
from app.models.inventory import InventoryItem
from app.models.recall import ECRIAlert
from app.services.matching_service import MatchingService


@dataclass
class _FakeRecall:
    recall_number: str
    manufacturer: str = ""
    product: str = ""
    model_number: str = ""
    catalog_number: str = ""
    udi: str = ""
    id: int = None
    raw_data: dict = field(default_factory=dict)


def _item(**kwargs) -> InventoryItem:
    defaults = dict(asset_number="A-1", manufacturer="", device_name="", model_number="", catalog_number="", udi="")
    defaults.update(kwargs)
    return InventoryItem(**defaults)


def test_udi_exact_match_wins_top_priority():
    engine = MatchingService(matched_threshold=90, possible_threshold=75)
    recall = _FakeRecall(recall_number="R1", udi="(01)12345", manufacturer="Acme", product="Totally Different Name")
    inventory = [_item(asset_number="A-1", udi="(01)12345", manufacturer="Other Co", device_name="Unrelated")]
    result = engine.match_one(recall, RecallSource.FDA, inventory)
    assert result.status == MatchStatus.MATCHED
    assert result.method == MatchMethod.UDI
    assert result.confidence_score == 100.0
    assert result.hospital_asset_number == "A-1"


def test_model_number_exact_match():
    engine = MatchingService(matched_threshold=90, possible_threshold=75)
    recall = _FakeRecall(recall_number="R2", model_number="XJ-500")
    inventory = [_item(asset_number="A-2", model_number="xj500")]
    result = engine.match_one(recall, RecallSource.FDA, inventory)
    assert result.status == MatchStatus.MATCHED
    assert result.method == MatchMethod.MODEL_NUMBER


def test_no_inventory_match_returns_not_matched():
    engine = MatchingService(matched_threshold=90, possible_threshold=75)
    recall = _FakeRecall(recall_number="R3", manufacturer="Zeta Medical", product="Infusion Pump 9000")
    inventory = [_item(asset_number="A-3", manufacturer="Completely Unrelated", device_name="Bed Frame")]
    result = engine.match_one(recall, RecallSource.FDA, inventory)
    assert result.status == MatchStatus.NOT_MATCHED
    assert result.hospital_asset_number == ""


def test_fuzzy_product_name_possible_match():
    engine = MatchingService(matched_threshold=95, possible_threshold=50)
    recall = _FakeRecall(recall_number="R4", product="Infusion Pump Model 9000")
    inventory = [_item(asset_number="A-4", device_name="Infusion Pump Mdl 9000")]
    result = engine.match_one(recall, RecallSource.FDA, inventory)
    assert result.status in (MatchStatus.MATCHED, MatchStatus.POSSIBLE_MATCH)
    assert result.confidence_score >= 50


def test_empty_inventory_list_is_not_matched_without_error():
    engine = MatchingService()
    recall = _FakeRecall(recall_number="R5")
    result = engine.match_one(recall, RecallSource.FDA, [])
    assert result.status == MatchStatus.NOT_MATCHED
    assert result.method == MatchMethod.NONE


def test_ecri_alert_uses_alert_number_not_recall_number():
    # Regression test: ECRIAlert has no `recall_number` attribute (it uses
    # `alert_number`); match_one/match_all must not assume every recall-like
    # object shares FDARecall's field name.
    engine = MatchingService(matched_threshold=90, possible_threshold=75)
    alert = ECRIAlert(alert_number="ECRI-9001", model_number="XJ-500")
    inventory = [_item(asset_number="A-9", model_number="XJ-500")]

    result = engine.match_one(alert, RecallSource.ECRI, inventory)
    assert result.recall_number == "ECRI-9001"
    assert result.status == MatchStatus.MATCHED

    results = engine.match_all([], [alert], inventory)
    assert len(results) == 1
    assert results[0].recall_number == "ECRI-9001"
