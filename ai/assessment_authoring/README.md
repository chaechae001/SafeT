# 위험성평가표 작성: 검색·추출·검증·계산 구현

공통 기준: 5a882f6148d614d341cbdbe9643967da2f915457 / 계약 PR #31.
이 모듈은 input_based 경로를 독립 실행한다. 기존 배포 7514acd의 질문·사용자 조치 확인·저장 API는 유지한다.

- 검색·근거·검증·계산(검색·통합 담당): 아래 "함수와 연결"부터 "검토와 표시"까지.
- LLM 추출(추출 담당): 아래 "추출 어댑터" 절.

## 실행

저장소 루트, Python 3.11 이상. 추가 패키지·GPU·배포·API 키 없이 실행한다.
모든 모듈과 테스트는 저장소 루트 기준 패키지 import(`ai.assessment_authoring`, `contracts.assessment_authoring.v1`)를 사용한다. sys.path를 바꾸지 않는다.

```bash
python -m unittest discover -s ai/assessment_authoring/tests -v   # 검색·계산 + 추출 테스트 함께 실행
python contracts/assessment_authoring/v1/validate.py
python -X utf8 -m ai.assessment_authoring.demo --case unknown
python -X utf8 -m ai.assessment_authoring.demo --case critical_supported
python -X utf8 -m ai.assessment_authoring.demo --case all_supported
```

demo의 입력·추출은 공통 합성 예제다. 검색·검증·계산·행 조립은 실제 구현을 실행한다.
unknown 사례는 FRY / S2 / C3 / 상, critical_supported는 C2 / 중, all_supported는 C1 / 중이다.
예상 위험도·사용자 확인 상태를 만들어 현재 등급을 덮어쓰지 않는다.

## 함수와 연결

| 파일 | 입력 → 출력 |
| --- | --- |
| retrieval_adapter.py | InputBundle + 카탈로그 → RetrievalBundle |
| analysis_validator.py | 입력·검색·분석·카탈로그 → 검증 및 unknown 정규화된 분석 복사본 |
| assessment_composer.py | 입력·검색·분석·카탈로그 → AssessmentCore, render_assessment는 표시용 행도 반환 |
| pipeline.py | build_context·extract_analysis 함수 주입 → 입력/검색/분석/결과/검색 이력 |
| mappings/catalog_links.json | 표준 기기 ID·보수적 키워드 → 카탈로그 시나리오 ID |

입력 담당은 build_context를, 추출 담당은 extract_analysis를 구현한 뒤 run_pipeline에 넘긴다.
3개씩 후보를 나누고 전체 배치를 처리한다. 후보 0건에는 모델을 호출하지 않는다.
결과 전체를 DB 응답으로 바로 보내지 않는다. 기존 서비스의 revision·소유권·모드별 저장 게이트 연결은 후속 통합 대상이다.

## 기존 RAG 연결

백엔드 환경에서는 기존 services.rag_retrieval.candidates를 rag_provider 인자로 전달한다.
실제 데이터는 SAFET_RAG_DIR에 설정된 기존 비공개 인덱스·MANIFEST를 사용하며 해당 함수의 무결성 검사를 재사용한다.

```python
bundle, trace = retrieve_with_evidence(
    context, catalog,
    rag_provider=rag_retrieval.candidates,
    rag_links=verified_equipment_hazard_links,
)
```

rag_links는 {"기기ID:실제위험코드": ["시나리오ID"]} 형태의 검수된 연결표다.
위험코드를 시나리오 ID로 추정하거나 임의 출처를 카탈로그 문서 쪽으로 바꾸지 않는다.
실제 위험코드와 출처 응답은 trace.rag_response에 보존하고, 미연결 매핑은 trace.diagnostics에 남긴다.
현재 저장소에 비공개 인덱스가 없으므로 실제 코드별 연결표를 만들어냈다고 주장하지 않는다.
합성 응답 주입 테스트는 API 연결 형태와 이력 보존을 확인한다.

기본 검색의 source_refs는 기존 카탈로그의 등록 문헌 위치다. matched는 참조 연결을 뜻하며 원문 실시간 조회나 현장 사실 검증을 뜻하지 않는다.
RAG 공급자가 설정되지 않으면 카탈로그 검색만 실행하고 trace.retrieval_mode=catalog로 기록한다.
명시적으로 공급자를 전달했는데 실패하면 예외를 전달한다. 장애를 정상 0건으로 처리하지 않는다.
검색 원문 이력에는 비공개 자료가 포함될 수 있으므로 공개 로그·PR·클라이언트에 그대로 노출하지 않는다.

## 범위와 남은 검수

- 기기 매핑은 보수적인 시작 집합이다. 미등록 관계는 unmatched로 남긴다. 일반 냉장고를 냉동실 내부 작업으로 연결하지 않는다.
- 키워드·간단한 부재 표현으로 후보를 찾는다. 문맥 전체·복합 부정·조치 전체 조건의 의미 검증은 추출 품질 검사 대상이다.
- 법령 registry는 기본 빈 목록이다. 검수된 시행일·적용조건을 거친 registry만 서버에서 주입한다.
- 현재 조치의 직접 인용은 문자열·자료 유형·ID를 검사한다. 진술의 진실성까지 검증하는 기능은 아니다.
- 성공 행은 상/중/하, 일부 미매칭은 partial, 결과 없음은 no_supported_result다.
- MATRIX는 backend/domain/risk_policy.py를 import한다. 원본 정책과 수동 evaluate는 변경하지 않는다.
- 공통 검사의 스냅샷 해시는 LF 기준이다. Windows CRLF 체크아웃에서도 동일한 원문을 검사하도록 보정했다.

## 검사 결과

검색·계산 unittest 27개와 추출 unittest 22개(합계 49개)를 함께 실행한다. 검색·계산 쪽 범위: 공통 예제 5종, 등급표 9조합, ID·근거·질문·중복 거절,
누락 조치, 법령 등록, 배치 보존, 기기 오매핑 반례, RAG 실패/미매핑/이력,
추천과 현재 등급 분리, 고정 함수 연결, 모델 호출 생략.
공통 계약 33개와 저장소 지정 CPU self-test 3개도 실행한다.
실제 클라우드·DB·PDF·QR·실모델 검사는 포함하지 않는다. 기존 검수 배포와 병행 가능하다.


## 검토와 표시

출력은 담당자가 실제 작업과 근거를 검토할 초안이다. 기기에서 찾았지만 작업이 미확인인 후보와 입력에서 작업을 부정한 후보는 공통 결과인 core.review_candidates에 각각 work_unconfirmed와 input_denies_work로 담는다. 담당자가 실제 작업 확인 또는 비적용 결정을 내리기 전까지 검토 대상으로 남는다. 검색 진단은 retrieval_trace에 기록하며 실제 미매칭 위험만 평가표에 표시한다.
source_refs는 등록된 카탈로그 순서의 처음 두 건이다. 검색 관련도 순위를 뜻하지 않는다.
계약·원문 근거 검사는 #31과 같은 함수를 사용한다. 서비스 저장·확정 연결 시 권한, revision, 검토 이력, 명시적 확정을 서버에서 확인한다.

## 추출 어댑터

`extraction_adapter.py`는 입력·검색 후보·카탈로그 조치 정의를 기존 EXAONE 연결에 전달하고 `analysis.schema.json`을 만족하는 AnalysisBundle을 반환한다.
작업 지시: [tasks/03-extraction.md](../../contracts/assessment_authoring/v1/tasks/03-extraction.md).

### 호출

```python
from ai.assessment_authoring.extraction_adapter import extract_analysis, run_extraction, ExtractionError

analysis = extract_analysis(context, retrieval_bundle, catalog_snapshot)          # AnalysisBundle (run_pipeline에 그대로 주입)
result = run_extraction(context, retrieval_bundle, catalog_snapshot, call_model)  # .analysis, .runs, .work_review_candidates
```

- `call_model(messages) -> {"content", "finish_reason", "usage", "model", "max_tokens"}`. 생략하면 `exaone_chat`.
- 후보를 3개씩 나누어 배치당 호출 1회. 후보가 없거나 텍스트·전사 media가 없으면(사진·기기 목록만) 모델을 호출하지 않는다.
- `unmatched_risks` = `retrieval.unmatched` + 모델 미매칭(중복 제거).
- `runs`: 배치별 scenario_ids·모델·max_tokens·finish_reason·usage·prompt_version·prompt_sha256.
- `work_review_candidates`: 보조 진단. 이 호출의 검색 후보 중 analysis에서 빠진 scenario_id이며 사유를 구분하지 않는다. 담당자 검토 대상의 공식 결과는 `run_pipeline`이 만드는 `core.review_candidates`(`work_unconfirmed` / `input_denies_work`)다.
- 인용은 공통 `validate.py`의 `whole_sentence`로 검사한다. 원문 한 문장(문장부호까지)과 같아야 하므로 부정문 일부("보호구를 착용")는 조치 근거가 되지 않는다.
- 실패는 `ExtractionError(code, detail)`로 던진다. detail에 모델 원문·안내 문구·설정값을 넣지 않는다.

| code | 상황 |
| --- | --- |
| INPUT_INVALID | 입력·검색 Bundle 스키마 위반, 카탈로그 밖 후보, 정책 버전 불일치 |
| INPUT_TOO_LONG | backend `AI_INPUT_TOO_LONG`: 입력이 4096 토큰 예산을 넘음 |
| MODEL_UNCONFIGURED | backend `AI_UNCONFIGURED` 등 설정 오류, backend 모델 연결 import 실패 |
| MODEL_TOKENIZE_FAILED | backend `AI_TOKENIZE_FAILED`: 토큰 계수 경로 실패 |
| MODEL_REQUEST_FAILED | HTTP·응답 본문 오류 |
| MODEL_OUTPUT_TRUNCATED | finish_reason=length (응답 중단) |
| MODEL_OUTPUT_INCOMPLETE | stop 이외의 종료 사유 |
| MODEL_OUTPUT_INVALID_JSON | 빈 응답, JSON 파싱 실패, 객체가 아님, JSON 뒤 추가 문장 |
| MODEL_OUTPUT_SCHEMA | grade/severity 등 추가 필드, questions≠[], 잘못된 state |
| MODEL_OUTPUT_REFERENCE | 배치 밖·중복 scenario, 미등록·중복 control, 없는 media, 위조·문장 일부 인용, 텍스트·전사 문장 없는 작업 근거, 탐지·보유 참조의 조치 판정 |

### 모델 설정

`exaone_chat`은 `backend/services/catalog_ai.py`의 설정·인증·토큰 계수를 그대로 사용한다. backend 프로세스(작업 디렉터리 `backend/`, 저장소 루트도 import 경로에 포함)에서 호출한다.

| 항목 | 값 |
| --- | --- |
| 모델 | `SAFET_AI_MODEL` (현재 팀 설정: EXAONE 3.5) |
| 주소 | `SAFET_AI_BASE_URL` 또는 `SAFET_AI_GATEWAY_URL` |
| 출력 한도 | `SAFET_AI_MAX_TOKENS`(256~2048, 기본 1024), 토큰 계수 후 입력+출력 4096 이내 |
| 생성 | temperature 0, `response_format: json_object` |
| 프롬프트 | `system_prompt.md` (`assessment-extraction-2`) = 공통 `prompts/generation_system.txt`(계약 `5a882f6`) 12개 규칙 + 조치 근거 규칙 |

모델에는 시나리오 설명·조치 ID·핵심 여부·현재 조치 문구·문헌 참조만 보낸다. severity·initial_grade·plan_text는 보내지 않는다.
언급 없는 조치는 응답에서 생략하게 하여 출력 길이를 줄인다. 누락 조치는 validate_analysis가 unknown으로 정규화한다.

### 고정 사례

`fixtures/extraction/<사례>/`에 `input.json`, `retrieval.json`, `model_response.json`(mock 응답), `analysis.json`(어댑터 출력)이 있다. 모두 **합성 자료**이며 실제 모델 응답이나 현장 자료가 아니다.

| 사례 | 확인 내용 |
| --- | --- |
| normal | 원문 문장 인용이 있는 조치만 supported |
| unknown | 작업만 언급 → control_evidence 없음, assumptions 기록 |
| detection_only | 사진 탐지·기기 목록만 → 모델 호출 없음, 분석 행 없음. run_pipeline에서 FRY는 core.review_candidates(work_unconfirmed) |
| negation | 고장·미보유 진술 → not_effective |
| conflict | TEXT·VOICE 진술 상충 → unknown, 두 근거 보존 |
| composite_partial | 보안경/내열 보호구 중 일부만 확인 → unknown |
| no_match | 검색 후보 없음 → 모델 호출 없이 unmatched_risks 보존 |

### 추출 검사 범위

mock 응답으로 파싱·계약·오류 처리를 검사하고, `run_pipeline`에 이 어댑터를 넣어 검색→추출→계산 연결을 확인한다.
backend 설정·계수 오류의 ExtractionError 전달은 가짜 backend 모듈로 검사한다(네트워크 없음).
실제 EXAONE 호출 검사는 저장소의 호출 대기 조건이 해제된 뒤 별도로 실행·기록한다.

## RAG 문헌 전달

run_pipeline의 선택적 extract_with_evidence(context, batch, catalog, evidence) 콜백을 사용하면
시나리오별 실제 검색 문헌을 모델 입력에 전달할 수 있다. 기존 extract_analysis 3인자 계약은 유지한다.
live_text_check.build_messages의 document_evidence 인자는 문헌을 reference_documents로 구분한다.
최종 표시 행의 document_evidence에는 동일한 내용과 출처가 보존된다.
원본 집계 응답의 출처는 위험코드 묶음 단위다. source_evidence가 있으면 원본 연결 행의 문장·파일·쪽 정보를 함께 보존한다.
현장 조치 근거와 혼용하지 않는다. 미확인 조치의 개선 후보에도 실제 미실시를 단정하는 표현을 사용하지 않는다.
enabled=false 응답은 오류로 처리한다. 배포 웹앱의 RAG 설정은 이번 검수에서 변경하지 않았다.

### 실제 튀김기 검수 재실행

```bash
python -X utf8 -m ai.assessment_authoring.live_rag_check --env-file "<기존 backend/.env 경로>" --rag-file "<SSH로 읽은 실제 검색 응답.json>" --links-file "<manifest 해시를 확인한 연결 행.json>" --output "<저장소 밖 로컬 결과.json>"
```

links-file은 `{ "rows": [...] }` 형식이다. 검색 응답과 연결 행 파일은 같은 manifest의 retrieval 자료에서 확보한다.
evidence_qualification은 A등급의 기기 직접 언급 문장만 전달한다. 섹션명만으로 묶인 다른 기기 문장과 1:1 대응이 없는 대책 집계는 제외한다.
현재 검수 도구는 배치당 1개 시나리오로 기존 관문의 4,096 토큰 한도를 검사한다. 프롬프트·응답·문헌이 포함된 결과 파일은 비공개로 보관한다.
이 검수는 문헌 전달·계약·계산 연결을 확인하며, 원문 PDF 육안 검증이나 전체 기기 정확도 평가를 대신하지 않는다.
