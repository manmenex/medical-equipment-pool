import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


async def create(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    before_data: dict | None = None,
    after_data: dict | None = None,
    request_id: str | None = None,
    correlation_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    log = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_data=before_data,
        after_data=after_data,
        request_id=request_id,
        correlation_id=correlation_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(log)
    await db.flush()
    return log


async def list_logs(
    db: AsyncSession,
    *,
    entity_type: str | None = None,
    user_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AuditLog]:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())
