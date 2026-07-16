"""Configuration package - loads .env and exposes a typed Settings singleton."""

from app.config.settings import Settings, get_settings

__all__ = ["Settings", "get_settings"]
