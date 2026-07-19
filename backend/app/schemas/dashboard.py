from pydantic import BaseModel


class DashboardSummary(BaseModel):
    total: int
    available_at_pool: int
    issued_to_ward: int
    unavailable_defective: int
    decommissioned: int
    pm_due_soon: int
    cal_due_soon: int


class BorrowTrendPoint(BaseModel):
    date: str
    count: int


class TopBorrowedItem(BaseModel):
    equipment_id: str
    asset_number: str
    equipment_name: str
    borrow_count: int
