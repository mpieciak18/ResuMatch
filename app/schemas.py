from pydantic import BaseModel, field_validator
from typing import List


class AnalysisResult(BaseModel):
    score: int
    summary: str
    strengths: List[str]
    weaknesses: List[str]

    @field_validator("score")
    @classmethod
    def clamp_score(cls, v: int) -> int:
        return max(0, min(100, v))
