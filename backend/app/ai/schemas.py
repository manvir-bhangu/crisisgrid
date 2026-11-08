from typing import Literal
from pydantic import BaseModel, Field

Category = Literal["medical", "accident", "fire", "rescue", "other"]
Severity = Literal["low", "medium", "high", "critical"]
SEV_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


class Assessment(BaseModel):
    category: Category
    severity: Severity
    injuries: int | None = Field(default=None, ge=0, le=500)
    trapped: bool = False
    location_clues: list[str] = Field(default_factory=list, max_length=10)
    confidence: float = Field(ge=0, le=1)
    reasoning: str = Field(max_length=600)