"""Roadmap PR27/PR28 (Owner Governance 2026-11-25 D4, D7, D10, D11): shared
value types for the accessory/condition checklists, Cryo-Cuff cuff counts and
the ward-side contact name.

Two checklist shapes exist, selected by the equipment's category
(``equipment_categories.checklist_kind``) and told apart on the wire by a
``kind`` discriminator:

- ``standard``: screen_ok / charger_ok / clamp_ok (D4).
- ``cryo_cuff``: the six-item paper-form checklist plus per-type cuff counts
  (D10).

An individual item that is omitted inside a submitted checklist object
defaults to ``true`` (checked/normal, Owner UX answer 3). A checklist object
that is omitted entirely is stored as NULL = "not recorded".

Cuffs are accessories, never equipment: nothing here touches equipment state.
"""
from typing import Annotated, Literal, Union

from pydantic import BaseModel, BeforeValidator, Field, StrictBool

CHECKLIST_STANDARD = "standard"
CHECKLIST_CRYO_CUFF = "cryo_cuff"
CHECKLIST_KINDS = (CHECKLIST_STANDARD, CHECKLIST_CRYO_CUFF)
ChecklistKind = Literal["standard", "cryo_cuff"]

CUFF_TYPES = ("back_hip_rib", "knee", "shoulder", "ankle")
MAX_CUFFS_PER_TYPE = 99

CONTACT_NAME_MAX_LENGTH = 100


def _clean_contact_name(value: object) -> object:
    """Trim; blank becomes None (never required); reject over-long values and
    control characters rather than silently truncating."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("must be a string")
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > CONTACT_NAME_MAX_LENGTH:
        raise ValueError(f"must be at most {CONTACT_NAME_MAX_LENGTH} characters")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in cleaned):
        raise ValueError("must not contain control characters")
    return cleaned


# Optional free-text name of the ward staff member (D7). Ward staff are not
# application users; this is never a patient name.
ContactName = Annotated[str | None, BeforeValidator(_clean_contact_name)]


class CuffCounts(BaseModel):
    """Per-type cuff counts (D11). No individual cuff identity."""

    back_hip_rib: int = Field(default=0, ge=0, le=MAX_CUFFS_PER_TYPE)
    knee: int = Field(default=0, ge=0, le=MAX_CUFFS_PER_TYPE)
    shoulder: int = Field(default=0, ge=0, le=MAX_CUFFS_PER_TYPE)
    ankle: int = Field(default=0, ge=0, le=MAX_CUFFS_PER_TYPE)

    model_config = {"extra": "forbid"}

    def as_dict(self) -> dict[str, int]:
        return {t: getattr(self, t) for t in CUFF_TYPES}

    def total(self) -> int:
        return sum(self.as_dict().values())

    @classmethod
    def from_dict(cls, values: dict[str, int]) -> "CuffCounts":
        return cls(**{t: int(values.get(t, 0)) for t in CUFF_TYPES})


class StandardChecks(BaseModel):
    """D4: screen not cracked, charger cable intact, pole clamp present/OK."""

    kind: Literal["standard"]
    screen_ok: StrictBool = True
    charger_ok: StrictBool = True
    clamp_ok: StrictBool = True

    model_config = {"extra": "forbid"}

    def report_columns(self) -> dict[str, bool]:
        return {"screen": self.screen_ok, "charger": self.charger_ok, "clamp": self.clamp_ok}


class CryoCuffChecks(BaseModel):
    """D10: the six-item "Cryo-Cuff" paper form. ``cuffs`` are the per-type
    counts (issued at dispatch, returned at receipt)."""

    kind: Literal["cryo_cuff"]
    body_ok: StrictBool = True
    charger_ok: StrictBool = True
    lid_with_charger_ok: StrictBool = True
    lid_without_charger_ok: StrictBool = True
    hose_oring_ok: StrictBool = True
    cuff_ok: StrictBool = True
    cuffs: CuffCounts = Field(default_factory=CuffCounts)

    model_config = {"extra": "forbid"}

    def report_columns(self) -> dict[str, bool]:
        """D10 report mapping (PR30): items 1/2/3 feed the three shared
        columns; items 4-6 are stored only."""
        return {"screen": self.body_ok, "charger": self.charger_ok, "clamp": self.lid_with_charger_ok}


Checks = Annotated[Union[StandardChecks, CryoCuffChecks], Field(discriminator="kind")]


def report_columns(checks: dict | StandardChecks | CryoCuffChecks | None) -> dict[str, bool | None]:
    """Map a stored/parsed checklist to the three report columns
    (screen/charger/clamp); all None when the checklist was not recorded."""
    if checks is None:
        return {"screen": None, "charger": None, "clamp": None}
    if isinstance(checks, dict):
        if checks.get("kind") == CHECKLIST_CRYO_CUFF:
            checks = CryoCuffChecks.model_validate(checks)
        else:
            checks = StandardChecks.model_validate(checks)
    return checks.report_columns()
