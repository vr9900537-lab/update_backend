"""Compatibility exports for settings now defined in :mod:`app.config`."""

from app.config import Settings, get_settings

__all__ = ["Settings", "get_settings"]
