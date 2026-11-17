"""모델은 DB ID·확인 사실·미확인 정보만 반환한다. 등급과 출처는 서버 소유다."""
from typing import Annotated, Literal
from pydantic import Field
from schemas.assessment import StrictModel

Identifier = Annotated[str, Field(min_length=1,max_length=100)]
Statement = Annotated[str, Field(min_length=1,max_length=1000)]
class Evidence(StrictModel):
    id: Identifier
    media_id: Identifier
    kind: Literal['observed','reported']
    statement: Statement

class ControlFact(StrictModel):
    control_id: Identifier
    state: Literal['present','absent','unknown']
    evidence_ids: list[Identifier] = Field(max_length=30)

class ScenarioMatch(StrictModel):
    scenario_id: Identifier
    applicability: Literal['confirmed','possible']
    evidence_ids: list[Identifier] = Field(max_length=30)
    controls: list[ControlFact] = Field(min_length=1,max_length=50)
    uncertainties: list[Statement] = Field(max_length=20)

class Extraction(StrictModel):
    evidence: list[Evidence] = Field(max_length=300)
    matches: list[ScenarioMatch] = Field(max_length=26)
    unmatched_observations: list[Statement] = Field(max_length=50)
