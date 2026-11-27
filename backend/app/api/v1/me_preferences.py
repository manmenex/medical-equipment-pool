from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.db.session import get_db
from app.schemas.ui_preferences import UiPreferences

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/preferences", response_model=UiPreferences)
async def get_preferences(user=Depends(get_current_user)):
    return UiPreferences(**(user.ui_preferences or {}))


@router.put("/preferences", response_model=UiPreferences)
async def put_preferences(
    payload: UiPreferences, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)
):
    """Replace the caller's own theme. An empty body resets to defaults."""
    data = payload.model_dump(exclude_none=True)
    user.ui_preferences = data or None
    await db.commit()
    return UiPreferences(**data)
