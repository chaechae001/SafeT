"""작업 설명을 모델 입력 문장(input_segments) 단위로 나눈다."""
import re

_SPLIT = re.compile(r"(?<=[.!?。！？])\s+|\n+")


def split_sentences(text):
    return [part.strip() for part in _SPLIT.split(text) if part.strip()]
