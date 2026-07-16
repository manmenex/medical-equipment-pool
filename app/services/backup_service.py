"""Database backup service (FUNCTION 9 - Settings: Database Backup)."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from app.utils.logging_config import get_logger

logger = get_logger(__name__)


class BackupService:
    def __init__(self, database_path: Path, backup_dir: Path):
        self.database_path = Path(database_path)
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_backup(self) -> Path:
        """Copy the live SQLite file to a timestamped backup (safe: SQLite
        file copies are consistent as long as no write is mid-transaction;
        WAL checkpoint isn't strictly required for a desktop app backup
        button, but callers should avoid backing up mid-scrape)."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        destination = self.backup_dir / f"recall_monitor_backup_{timestamp}.db"
        shutil.copy2(self.database_path, destination)
        logger.info("Database backed up to %s", destination)
        return destination

    def list_backups(self) -> list[Path]:
        return sorted(self.backup_dir.glob("recall_monitor_backup_*.db"), reverse=True)
