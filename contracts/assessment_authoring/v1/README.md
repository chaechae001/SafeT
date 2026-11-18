# 위험성평가표 작성 솔루션 — AI·RAG 작업 묶음 v3

공통 시작: [START_HERE.md](START_HERE.md) · 연결 계약: [INTERFACES.md](INTERFACES.md) · 검토 결과: [REVIEW.md](REVIEW.md)

## 작업 흐름
입력·탐지 정리 → input.json → 검색·근거 연결 → retrieval.json → LLM 구조화 → analysis.json → 검증·계산·평가표·저장.

## 담당별 시작
| 역할 | 작업 지시 | 입력 | 제출 |
|---|---|---|---|
| 입력 담당 | tasks/01-input.md | 기존 원본 요청·탐지 응답 | input.json·매핑·입력 품질 검사 |
| 검색·통합 담당 | tasks/02-retrieval-integration.md | 고정 input/analysis | retrieval.json·평가표·통합 검사 |
| 추출 담당 | tasks/03-extraction.md | 고정 input/retrieval | analysis.json·프롬프트·추출 검사 |

1. 담당 작업 지시와 해당 Schema를 읽는다.
2. `python validate.py`를 실행한다. Python 3.11 이상, 추가 패키지 없음.
3. 공통 examples로 구현하고 실제 출력으로 교체한다.
4. 구현 코드·출력 JSON·실행 방법·검사 결과를 제출한다.

## 공통 파일
- PIPELINE.md: 세부 흐름·모델·계약.
- schemas/: input/retrieval/analysis/assessment JSON Schema.
- reference/catalog.json: 공통 기준. 직접 수정하지 않는다.
- reference/SOURCE.json: 원본 blob SHA·자료 기준 commit·자료 해시.
- examples/: 합성 입력·검색·분석·계산 예시 5세트와 입력 유형별 예제.
- prompts/generation_system.txt: 추출 System 프롬프트.
- GITHUB.md: 공통 시작과 파일 소유권.
- validate.py: 계약에 사용하는 Schema 키워드·ID·근거·계산 예시 검사.

## 계약
기존 input/retrieval/analysis 필드 구조를 유지하고 기기 enum·최소 입력·근거 개수 검사를 보강했다. assessment는 신규 내부 결과 계약이다. unknown은 실제 조치 부재가 아니며 계산에서만 미충족으로 처리한다.
LLM은 질문·등급을 생성하지 않는다. 최종 계산은 기존 CATALOG-MVP-1.1 MATRIX를 재사용한다.
expected.json은 계산 검사값이며 전체 HTTP 응답이 아니다.
이 검사로 실제 모델 정확도나 현장 사실을 검증했다고 해석하지 않는다.

