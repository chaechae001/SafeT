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
    # UX-017 03 기기: 이번 평가에만 추가한 기기(사업장 등록 기기는 서버가 넣음). 사업장 정보는 바꾸지 않는다.
    add_machine_codes: list[Annotated[str, Field(min_length=1, max_length=20)]] = Field(default_factory=list, max_length=100)
    add_custom_machines: list[Name] = Field(default_factory=list, max_length=30)

    @model_validator(mode='after')
    def inputs(self):
        if not (self.text or self.voice_text or self.photos or self.catalog_ids): raise ValueError('사진·전사문·글 또는 DB 작업 선택이 필요합니다.')
        if len(self.members) != len(set(self.members)): raise ValueError('참여자 이름이 중복됩니다.')
        self.add_custom_machines = list(dict.fromkeys(' '.join(n.split()) for n in self.add_custom_machines))
        self.add_machine_codes = list(dict.fromkeys(self.add_machine_codes))
        return self

class ActionEdit(StrictModel):
    id: int | None = None
    text: str = Field(min_length=1, max_length=500)
    checked: bool = False

class Owner(StrictModel):
    type: Literal['R','D']
    name: Name

class ItemEdit(StrictModel):
    work_reviewed: bool = False
    id: int = Field(gt=0)
    curr: list[ActionEdit] = Field(max_length=50)
    plans: list[ActionEdit] = Field(max_length=50)
    controls_reviewed: bool = False
    none: bool = False
    keep: Literal['Y','N'] | None = None
    owner: Owner | None = None
    due: date | None = None

    @model_validator(mode='after')
    def coherent(self):
        if self.none and any(a.checked for a in self.curr): raise ValueError('현재 조치 없음과 현재 조치를 동시에 선택할 수 없습니다.')
        return self

class SaveAssessment(StrictModel):
    excluded_review_candidates: list[str] | None = Field(default=None, max_length=100)
    revision: int = Field(ge=1)
    items: list[ItemEdit] = Field(max_length=100)

class RemoveRisk(StrictModel):
    """위험 항목 1개 삭제 (UX-005 · 화면수정요청 15). 작성 중 평가표만, revision 확인"""
    revision: int = Field(ge=1)

class AddRisk(StrictModel):
    revision: int = Field(ge=1)
    keyword: str = Field(min_length=1, max_length=200)

class PendingReview(StrictModel):
    """확인 대기(등록 기기 기준) 위험: add = 실제 작업으로 확인해 행 추가, dismiss = 하지 않는 작업이라 제외."""
    revision: int = Field(ge=1)
    scenario_id: str = Field(min_length=1, max_length=50)
    decision: Literal['add','dismiss']
