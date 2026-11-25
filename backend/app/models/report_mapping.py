"""Roadmap PR30 (D5): admin-editable ward -> daily-report-row mapping.

One optional override row per ward. A ward with no row (the default, no data
seeded) reports under its own name, grouped by its department; a row overrides
any of the three labels and the sort order. Reporting presentation only -- it
never affects dispatch/receipt, equipment state or any stored transaction.
"""
import uuid

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin


class ReportWardRow(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "report_ward_rows"
    __table_args__ = (UniqueConstraint("ward_id", name="uq_report_ward_rows_ward_id"),)

    ward_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("wards.id", ondelete="RESTRICT"), nullable=False)
    # NULL = fall back to the ward's own name / department name / blank.
    report_row_label: Mapped[str | None] = mapped_column(String(100))
    treatment_type: Mapped[str | None] = mapped_column(String(100))
    dispense_mode: Mapped[str | None] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
