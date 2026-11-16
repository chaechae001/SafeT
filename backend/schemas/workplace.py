"""사업장 요청·응답 형식 (B01 · B02 · B02-E · 화면설계서 08~09쪽)

테이블: workplaces(work_no, email, workplace, biz_code, use_yn) · workplace_machine(work_no, machine_code | NULL, machine_nm)
        biz_category(biz_code, biz_nm) · machine_category(machine_code, biz_code, machine_nm, use_yn)
"""
import re

from pydantic import BaseModel, Field, field_validator

NAME_MAX = 50           # workplaces.workplace · workplace_machine.machine_nm varchar(50)
CUSTOM_MAX_COUNT = 50   # 직접 추가 기기 최대 개수


def clean(v: str) -> str:
    """앞뒤 공백 제거, 가운데 공백은 하나로"""
    return re.sub(r"\s+", " ", (v or "").strip())


class BizCategory(BaseModel):
    biz_code: str
    biz_nm: str | None = None


class Machine(BaseModel):
    machine_code: str
    machine_nm: str | None = None


class WorkplaceMachine(BaseModel):
    machine_code: str | None = None      # 직접 추가한 기기는 null
    machine_nm: str | None = None
    custom: bool                         # 직접 추가 여부


class WorkplaceSave(BaseModel):
    """등록·수정 공통. 수정할 때 biz_code 는 바꿀 수 없음(보내도 무시하지 않고 검사)"""
    workplace: str
    machine_codes: list[str] = Field(default_factory=list)     # 업종 목록에서 체크한 기기
    custom_machines: list[str] = Field(default_factory=list)   # 목록에 없어 직접 추가한 기기 이름

    @field_validator("workplace")
    @classmethod
    def _name(cls, v: str) -> str:
        v = clean(v)
        if not v:
            raise ValueError("사업장명을 입력해 주세요.")
        if len(v) > NAME_MAX:
            raise ValueError(f"사업장명은 {NAME_MAX}자 이내로 입력해 주세요.")
        return v

    @field_validator("custom_machines")
    @classmethod
    def _custom(cls, v: list[str]) -> list[str]:
        out, seen = [], set()
        for name in v:
            name = clean(name)
            if not name:
                continue
            if len(name) > NAME_MAX:
                raise ValueError(f"기기 이름은 {NAME_MAX}자 이내로 입력해 주세요.")
            key = name.lower()
            if key not in seen:                     # 같은 이름은 합침
                seen.add(key)
                out.append(name)
        if len(out) > CUSTOM_MAX_COUNT:
            raise ValueError(f"직접 추가 기기는 {CUSTOM_MAX_COUNT}개까지예요.")
        return out


class WorkplaceCreate(WorkplaceSave):
    biz_code: str


class WorkplaceInfo(BaseModel):
    work_no: int
    workplace: str | None = None
    biz_code: str
    biz_nm: str | None = None
    machines: list[WorkplaceMachine]
    draft_count: int                     # 이 사업장에 연결된 작성 중 평가표 수 (삭제 확인 창 안내용)


class WorkplaceCreated(BaseModel):
    work_no: int
