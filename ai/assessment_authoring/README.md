# 위험성평가 추출 어댑터

입력·검색 후보·카탈로그 조치 정의를 기존 EXAONE 연결에 전달하고 `analysis.schema.json`을 만족하는 AnalysisBundle을 반환한다.
계약은 [contracts/assessment_authoring/v1](../../contracts/assessment_authoring/v1/README.md), 작업 지시는 [tasks/03-extraction.md](../../contracts/assessment_authoring/v1/tasks/03-extraction.md)를 따른다.

## 호출

```python
from extraction_adapter import extract_analysis, run_extraction, ExtractionError

analysis = extract_analysis(context, retrieval_bundle, catalog_snapshot)          # AnalysisBundle
result = run_extraction(context, retrieval_bundle, catalog_snapshot, call_model)  # .analysis, .runs
```

- `catalog_snapshot`: `reference/catalog.json`과 같은 형식(`policy_version`, `scenarios`).
- `call_model(messages) -> {"content", "finish_reason", "usage", "model", "max_tokens"}`. 생략하면 `exaone_chat`.
- 검색 후보를 3개씩 나누어 배치당 호출 1회를 수행하고 scenario_id 순서대로 합친다. 후보가 없으면 호출하지 않는다.
- `unmatched_risks` = `retrieval.unmatched` + 모델 미매칭(중복 제거).
- `runs`: 배치별 scenario_ids·모델·max_tokens·finish_reason·usage·prompt_version·prompt_sha256.
- 실패는 `ExtractionError(code, detail)`로 던진다. detail에 모델 원문을 넣지 않는다.

| code | 상황 |
| --- | --- |
| INPUT_INVALID | 입력·검색 Bundle 스키마 위반, 카탈로그 밖 후보, 정책 버전 불일치 |
| MODEL_REQUEST_FAILED | HTTP·응답 본문 오류 |
| MODEL_OUTPUT_TRUNCATED | finish_reason=length (응답 중단) |
| MODEL_OUTPUT_INCOMPLETE | stop 이외의 종료 사유 |
| MODEL_OUTPUT_INVALID_JSON | 빈 응답, JSON 파싱 실패, 객체가 아님, JSON 뒤 추가 문장 |
| MODEL_OUTPUT_SCHEMA | grade/severity 등 추가 필드, questions≠[], 잘못된 state |
| MODEL_OUTPUT_REFERENCE | 배치 밖·중복 scenario, 미등록·중복 control, 없는 media, 위조 인용, 탐지·보유 근거의 supported |

## 모델 설정

`exaone_chat`은 `backend/services/catalog_ai.py`의 설정·인증·토큰 계수를 그대로 사용한다. backend 프로세스(작업 디렉터리 `backend/`)에서 호출한다.

| 항목 | 값 |
| --- | --- |
| 모델 | `SAFET_AI_MODEL` (현재 팀 설정: EXAONE 3.5) |
| 주소 | `SAFET_AI_BASE_URL` 또는 `SAFET_AI_GATEWAY_URL` |
| 출력 한도 | `SAFET_AI_MAX_TOKENS`(256~2048, 기본 1024), 토큰 계수 후 입력+출력 4096 이내 |
| 생성 | temperature 0, `response_format: json_object` |
| 프롬프트 | `system_prompt.md` (`assessment-extraction-1`), 공통 `prompts/generation_system.txt` 12개 규칙 + 조치 근거 규칙 |

모델에는 시나리오 설명·조치 ID·핵심 여부·현재 조치 문구·문헌 참조만 보낸다. severity·initial_grade·plan_text는 보내지 않는다.
언급 없는 조치는 응답에서 생략하게 하여 출력 길이를 줄인다. 누락 조치는 compose_assessment가 unknown으로 정규화한다.

## 검사

```bash
python contracts/assessment_authoring/v1/validate.py
python -m unittest discover -s ai/assessment_authoring/tests -v
```

표준 라이브러리만 사용하며 모델을 호출하지 않는다(mock 검사).
실제 EXAONE 호출 검사는 저장소의 호출 대기 조건이 해제된 뒤 별도로 실행·기록한다.

## 고정 사례

`fixtures/extraction/<사례>/`에 `input.json`, `retrieval.json`, `model_response.json`(mock 응답), `analysis.json`(어댑터 출력)이 있다.
모두 **합성 자료**이며 실제 모델 응답이나 현장 자료가 아니다.

| 사례 | 확인 내용 |
| --- | --- |
| normal | 원문 직접 인용이 있는 조치만 supported |
| unknown | 작업만 언급 → control_evidence 없음, assumptions 기록 |
| detection_only | 사진 탐지·기기 목록만 → 조치 판정 없음 |
| negation | 고장·미보유 진술 → not_effective |
| conflict | TEXT·VOICE 진술 상충 → unknown, 두 근거 보존 |
| composite_partial | 보안경/내열 보호구 중 일부만 확인 → unknown |
| no_match | 검색 후보 없음 → 모델 호출 없이 unmatched_risks 보존 |
