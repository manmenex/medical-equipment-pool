"""Roadmap PR29: request-side HN field type.

``HnInput`` trims, maps blank to ``None`` and validates the light format; the
validation message never contains the value (the app's 422 handler also drops
``input``). Fields using it must be declared with ``HN_FIELD`` so the value is
excluded from ``model_dump`` (hence from the sync payload that is hashed and
stored in the ``client_operations`` ledger) and from ``repr``.
"""
from typing import Annotated

from pydantic import BeforeValidator, Field

from app.core.hn_crypto import normalize_hn


def _normalize(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("HN must be text")
    return normalize_hn(value)


HnInput = Annotated[str | None, BeforeValidator(_normalize)]

# default None, never in model_dump()/repr().
HN_FIELD = Field(default=None, exclude=True, repr=False)
