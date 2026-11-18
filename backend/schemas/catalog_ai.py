"""AI는 카탈로그 후보와 입력 근거만 반환한다. 등급·체크 상태는 출력 대상이 아니다."""
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field

Text = Annotated[str, Field(min_length=1, max_length=2000)]
Identifier = Annotated[str, Field(min_length=1, max_length=80, pattern=r'^[A-Za-z0-9_:.-]+$')]

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

class Evidence(Strict):
    media_id: Identifier
    statement: Text

class Question(Strict):
    id: Identifier
    text: Text

class Candidate(Strict):
    scenario_id: Identifier
    rationale: Text
    evidence: list[Evidence] = Field(min_length=1, max_length=20)
    questions: list[Question] = Field(max_length=11)

class Analysis(Strict):
    candidates: list[Candidate] = Field(min_length=1, max_length=26)
    unmatched_risks: list[Text] = Field(max_length=20)

class Answer(Strict):
    item_id: int = Field(gt=0)
    question_id: Identifier
    answer: Text

class RiskAnswers(Strict):
    revision: int = Field(ge=1)
    answers: list[Answer] = Field(min_length=1, max_length=100)

class Detection(Strict):
    photo_id: Identifier
    equipment: Annotated[str, Field(min_length=1, max_length=100)]
    confidence: float = Field(ge=0, le=1)

class DetectionResult(Strict):
    model: Annotated[str, Field(min_length=1, max_length=200)]
    detections: list[Detection] = Field(max_length=100)


# 배포 SAM 응답의 추가 메타데이터는 보존하고 서비스에 필요한 필드는 검증한다.
class SamBase(BaseModel):
    model_config = ConfigDict(extra='allow')

class SamDetector(SamBase):
    model_name: Text

class SamPhoto(SamBase):
    photo_id: Identifier
    status: str
    error_code: str | None = None
    width: int = Field(gt=0)
    height: int = Field(gt=0)

class SamDetection(SamBase):
    detection_id: Identifier
    photo_id: Identifier
    equipment_id: Annotated[str, Field(pattern=r'^EQ_[A-Z0-9_]+$')] | None
    detector_class: Text
    confidence: float = Field(ge=0,le=1)
    bbox: list[Annotated[float, Field(ge=0,le=1)]] = Field(min_length=4,max_length=4)

class SamOutput(SamBase):
    request_id: str
    status: str
    error_code: str | None = None
    detector: SamDetector
    photos: list[SamPhoto] = Field(max_length=8)
    detections: list[SamDetection] = Field(max_length=1000)

class SamResponse(SamBase):
    model_output: SamOutput
    service_meta: dict = Field(default_factory=dict)
