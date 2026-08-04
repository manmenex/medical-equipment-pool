from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import every model module so Base.metadata is fully populated for
# Alembic autogenerate and for `create_all` in tests.
from app.models import (  # noqa: E402,F401
    audit,
    equipment,
    import_session,
    master_data,
    notification,
    transaction,
    user,
)
