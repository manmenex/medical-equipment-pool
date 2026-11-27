from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

HEX = r"^#[0-9a-fA-F]{6}$"


class UiPreferences(BaseModel):
    """Personal theme. Unknown keys are rejected; every field is optional."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["system", "light", "dark", "custom"] | None = None
    bg: str | None = Field(default=None, pattern=HEX)
    surface: str | None = Field(default=None, pattern=HEX)
    text: str | None = Field(default=None, pattern=HEX)
    accent: str | None = Field(default=None, pattern=HEX)
    font_size: int | None = Field(default=None, ge=14, le=22)
    font_family: Literal["default", "system", "serif"] | None = None
