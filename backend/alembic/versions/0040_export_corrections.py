"""Export API correction events (Owner Governance 2026-11-27, D28)

Revision ID: 0040_export_corrections
Revises: 0039_transaction_corrections
Create Date: 2026-11-27

- `export_events.correction` BOOLEAN NOT NULL DEFAULT false
- `export_events.corrects_event_id` UUID NULL (event_id of the original)
- `export_events.withdrawn` BOOLEAN NOT NULL DEFAULT false (original voided
  inside its hold-back window: never exposed)
- drops `uq_export_events_transaction_type` (a transaction can be received
  again after a receipt void) and adds the partial unique index
  `uq_export_events_corrects_event_id` (one compensating event per original).

`generation` + partial unique index `uq_export_events_tx_type_generation`
  keep a retried normal dispatch/receipt emit from duplicating.

Downgrade (lossy, by design: the old schema cannot represent them) deletes correction rows, restores the old unique constraint after
removing superseded duplicates (keeps the latest non-withdrawn row per
(transaction, type)), and drops the columns.

Only runs raw SQL against PostgreSQL (dialect-gated like 0002-0039).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0040_export_corrections"
down_revision: Union[str, None] = "0039_transaction_corrections"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for stmt in (
        "ALTER TABLE export_events ADD COLUMN IF NOT EXISTS correction BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE export_events ADD COLUMN IF NOT EXISTS corrects_event_id UUID NULL",
        "ALTER TABLE export_events ADD COLUMN IF NOT EXISTS withdrawn BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE export_events ADD COLUMN IF NOT EXISTS generation INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE export_events DROP CONSTRAINT IF EXISTS uq_export_events_transaction_type",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_export_events_tx_type_generation ON export_events "
        "(transaction_id, event_type, generation) "
        "WHERE correction = false AND withdrawn = false AND event_type IN ('dispatch', 'receipt')",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_export_events_corrects_event_id "
        "ON export_events (corrects_event_id) WHERE corrects_event_id IS NOT NULL",
    ):
        op.execute(sa.text(stmt))


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for stmt in (
        "DELETE FROM export_events WHERE correction",
        "DELETE FROM export_events WHERE withdrawn",
        "DELETE FROM export_events e USING export_events n WHERE e.transaction_id = n.transaction_id "
        "AND e.event_type = n.event_type AND e.seq < n.seq",
        "DROP INDEX IF EXISTS uq_export_events_corrects_event_id",
        "DROP INDEX IF EXISTS uq_export_events_tx_type_generation",
        "ALTER TABLE export_events DROP COLUMN IF EXISTS generation",
        "ALTER TABLE export_events ADD CONSTRAINT uq_export_events_transaction_type UNIQUE (transaction_id, event_type)",
        "ALTER TABLE export_events DROP COLUMN IF EXISTS withdrawn",
        "ALTER TABLE export_events DROP COLUMN IF EXISTS corrects_event_id",
        "ALTER TABLE export_events DROP COLUMN IF EXISTS correction",
    ):
        op.execute(sa.text(stmt))
