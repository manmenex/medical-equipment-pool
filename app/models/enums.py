"""Shared enumerations used across models, services and the UI."""

from __future__ import annotations

from enum import Enum


class RecallSource(str, Enum):
    FDA = "FDA"
    ECRI = "ECRI"


class MatchStatus(str, Enum):
    MATCHED = "Matched"
    POSSIBLE_MATCH = "Possible Match"
    NOT_MATCHED = "Not Matched"


class MatchMethod(str, Enum):
    """Priority cascade used by the matching engine (FUNCTION 4)."""

    UDI = "UDI"
    MODEL_NUMBER = "Model Number"
    CATALOG_NUMBER = "Catalog Number"
    MANUFACTURER = "Manufacturer"
    PRODUCT_NAME = "Product Name"
    FUZZY = "Fuzzy Matching"
    NONE = "None"


class SchedulerFrequency(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class ReportFormat(str, Enum):
    EXCEL = "excel"
    PDF = "pdf"
    CSV = "csv"
