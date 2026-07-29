from pydantic import BaseModel

from app.schemas.common import UUIDStr


class ReportOperatorOut(BaseModel):
    """Roadmap PR17 Slice 2 (docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md
    §10.4): the bounded, report-scoped operator shape returned by
    `GET /report-options/operators`. Deliberately excludes
    `employee_code`/`email`/`phone`/`role`/any authentication metadata --
    all of which the existing, Administrator-only `UserOut`
    (`app/schemas/master_data.py`) already includes and this endpoint must
    not leak. `id` is the stable identifier (`User.id`), never
    `employee_code`/`email`.
    """

    id: UUIDStr
    display_name: str
    is_active: bool

    model_config = {"from_attributes": True}
