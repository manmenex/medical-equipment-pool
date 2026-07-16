from pydantic import BaseModel


class DashboardSummary(BaseModel):
    total: int
    available: int
    borrowed: int
    cleaning: int
    pm: int
    calibration: int
    repair: int
    out_of_service: int
    lost: int
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
