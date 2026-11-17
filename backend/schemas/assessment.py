"""평가표 작성 API 전용 계약. AI 판정 필드는 클라이언트 수정 대상이 아님."""
import base64
from datetime import date
from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Name = Annotated[str, Field(min_length=1, max_length=50)]
class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

class Photo(StrictModel):
    name: str = Field(max_length=100)
    place: str = Field(default='', max_length=100)
    data: str = Field(max_length=2800000)

    @field_validator('data')
    @classmethod
    def image_only(cls, value):
        try:
            header, encoded = value.split(',', 1)
            raw = base64.b64decode(encoded, validate=True)
            valid = ((header == 'data:image/png;base64' and raw.startswith(b'\x89PNG\r\n\x1a\n')) or
                     (header == 'data:image/jpeg;base64' and raw.startswith(b'\xff\xd8\xff')) or
                     (header == 'data:image/webp;base64' and raw[:4] == b'RIFF' and raw[8:12] == b'WEBP'))
            if not valid or len(raw) > 2 * 1024 * 1024: raise ValueError()
        except (ValueError, TypeError):
            raise ValueError('PNG/JPEG/WebP 사진만 허용하며 사진당 2MB 이하입니다.')
        return value

class CreateAssessment(StrictModel):
    catalog_ids: list[Annotated[str, Field(min_length=1, max_length=60)]] = Field(default_factory=list, max_length=100)
    request_key: UUID
    work_no: int = Field(gt=0)
    eval_dt: date
    eval_writer: Name
    members: list[Name] = Field(default_factory=list, max_length=30)
    text: str = Field(default='', max_length=10000)
    voice_text: str = Field(default='', max_length=10000)
    photos: list[Photo] = Field(default_factory=list, max_length=6)

    @model_validator(mode='after')
    def inputs(self):
        if not (self.text or self.voice_text or self.photos or self.catalog_ids): raise ValueError('사진·전사문·글 또는 DB 작업 선택이 필요합니다.')
        if len(self.members) != len(set(self.members)): raise ValueError('참여자 이름이 중복됩니다.')
        return self

class ActionEdit(StrictModel):
    id: int | None = None
    text: str = Field(min_length=1, max_length=500)
    checked: bool = False

class Owner(StrictModel):
    type: Literal['R','D']
    name: Name

class ItemEdit(StrictModel):
    id: int = Field(gt=0)
    curr: list[ActionEdit] = Field(max_length=50)
    plans: list[ActionEdit] = Field(max_length=50)
    none: bool = False
    keep: Literal['Y','N'] | None = None
    owner: Owner | None = None
    due: date | None = None

    @model_validator(mode='after')
    def coherent(self):
        if self.none and any(a.checked for a in self.curr): raise ValueError('현재 조치 없음과 현재 조치를 동시에 선택할 수 없습니다.')
        return self

class SaveAssessment(StrictModel):
    revision: int = Field(ge=1)
    items: list[ItemEdit] = Field(max_length=100)

class AddRisk(StrictModel):
    revision: int = Field(ge=1)
    keyword: str = Field(min_length=1, max_length=200)

class RiskAnswer(StrictModel):
    question_id: str = Field(min_length=1,max_length=100)
    answer: str = Field(min_length=1,max_length=2000)

class AnswerRisk(StrictModel):
    revision: int = Field(ge=1)
    answers: list[RiskAnswer] = Field(default_factory=list,max_length=100)
    additional_text: str = Field(default='',max_length=10000)
