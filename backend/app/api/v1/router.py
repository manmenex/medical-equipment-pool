from fastapi import APIRouter

from app.api.v1 import (
    audit,
    auth,
    borrow,
    dashboard,
    equipment,
    health,
    import_foundation,
    inventory_import,
    master_data,
    notifications,
    report_options,
    reports,
    transactions,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(equipment.router)
api_router.include_router(borrow.router)
api_router.include_router(transactions.router)
api_router.include_router(dashboard.router)
api_router.include_router(reports.router)
api_router.include_router(report_options.router)
api_router.include_router(users.router)
api_router.include_router(master_data.router)
api_router.include_router(audit.router)
api_router.include_router(notifications.router)
api_router.include_router(inventory_import.router)
api_router.include_router(import_foundation.router)
