from fastapi import APIRouter

from app.api.v1 import (
    audit,
    auth,
    borrow,
    dashboard,
    equipment,
    health,
    import_sessions,
    inventory_import,
    legacy_history_import,
    legacy_migration_authorities,
    legacy_reconciliation,
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
api_router.include_router(import_sessions.router)
api_router.include_router(legacy_migration_authorities.router)
api_router.include_router(legacy_history_import.router)
api_router.include_router(legacy_reconciliation.runs_router)
api_router.include_router(legacy_reconciliation.findings_router)
