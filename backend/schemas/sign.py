"""참여자 서명 API 계약 (SIGN · 화면설계서 29쪽)"""
import base64
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# 서명 이미지 data URL 길이 상한 (PNG 약 220KB). 화면 canvas 서명은 보통 10~60KB
MAX_SIGN_URL = 300_000


class SaveSign(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    member_no: int = Field(gt=0)
    # 확인 문구는 '결과와 계획을 확인' 한 가지. 체크하지 않으면 저장하지 않음
    confirm: Literal[True]
    sign_img: str = Field(max_length=MAX_SIGN_URL)

    @field_validator('sign_img')
    @classmethod
    def png_only(cls, value):
        try:
            header, encoded = value.split(',', 1)
            raw = base64.b64decode(encoded, validate=True)
            if header != 'data:image/png;base64' or not raw.startswith(b'\x89PNG\r\n\x1a\n') or len(raw) < 100:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError('서명 이미지가 올바르지 않아요. 서명 칸에 다시 서명해 주세요.')
        return value
