# 공통 입출력과 연결 계약

계약 버전은 `assessment-authoring-1`, 검토 묶음은 `v3-reviewed`다. 본 폴더는 구현 지침·Schema·합성 예제·검사 도구이며 서비스 어댑터는 각 담당자가 구현한다.

## 함수 경계

| 구현 담당 | 함수 | Input | Output |
| --- | --- | --- | --- |
| 입력 | build_context(raw_request, detection_result=None) | 기존 CreateAssessment 요청·기기 목록·탐지 결과 | InputBundle |
| 검색·통합 | retrieve_evidence(context, catalog_snapshot) | InputBundle·카탈로그 | RetrievalBundle |
| 추출 | extract_analysis(context, retrieval_bundle, catalog_snapshot) | 입력·후보·해당 조치 정의 | AnalysisBundle |
| 검색·통합 | compose_assessment(context, retrieval_bundle, analysis_bundle, catalog_snapshot) | 검증할 세 Bundle·카탈로그 | AssessmentCore |
| 검색·통합 | 서비스 호출부 | AssessmentCore·입력·근거·분석 | 기존 상세 응답·저장 JSON |

호출 순서: build_context → retrieve_evidence → extract_analysis → compose_assessment → 기존 API/DB 매핑.
compose_assessment는 LLM을 다시 호출하지 않는다. 검증·누락 조치 정규화·계산·핵심 결과 조립만 수행한다.
모든 함수는 새로 구현할 인터페이스다. 현재 서비스에 이미 존재하는 것으로 가정하지 않는다.

## 읽을 파일

- InputBundle: `schemas/input.schema.json`, `examples/*/input.json`.
- RetrievalBundle: `schemas/retrieval.schema.json`, `examples/*/retrieval.json`.
- AnalysisBundle: `schemas/analysis.schema.json`, `examples/*/analysis.json`.
- AssessmentCore: `schemas/assessment.schema.json`, `examples/*/assessment.json`.
- 기존 `expected.json`은 한 행의 계산값이다. HTTP 전체 응답이 아니다.
- 카탈로그: `reference/catalog.json`. 원본: `contracts/catalog_risk/catalog.json`.
- 원본 SHA·해시: `reference/SOURCE.json`. base_commit은 원본 자료 기준이며 팀 개발 시작 커밋은 START_HERE.md에 따른다.

## 입력·근거

media는 최소 1개다. 텍스트·전사 원문과 부정·수치를 보존한다. 사진만 입력되면 탐지 요약을 media에 넣는다.
kind는 text / voice_transcript / equipment_detection / equipment_inventory다.
사업장 기기 목록은 equipment_inventory로 구분한다. 탐지·보유 정보는 기능 작동이나 조치 실행 증거가 아니다.
equipment_ids는 reference/equipment_ids.json의 ID만 사용하며 중복을 제거한다. 글만 있으면 빈 배열이 가능하다.
사진 탐지 0건은 “탐지된 기기 없음” 요약으로 남기고 탐지 오류와 구분한다. 빈 입력·파일/모델 오류는 성공 Bundle 대신 기존 오류 경로로 반환한다.

작업 적용의 근거로 텍스트·전사에서 온전한 문장이나 한 줄을 인용한다. 조치 supported/not_effective의 참조는 텍스트·전사만 허용한다.
supported/not_effective의 statement도 참조 text/voice_transcript에 실제 존재하는 직접 인용이어야 한다.
unknown의 statement는 부족·상충 이유이며 evidence_refs=[]가 가능하다. 조치가 응답에서 누락되면 unknown으로 정규화한다.
잘못된 ID·위조 인용·중복은 오류다. 잘못된 supported를 조용히 unknown으로 바꾸어 성공시키지 않는다.
문자열 포함 검사는 현장 진실·복합 조치 전체 충족·부정 해석을 보장하지 않는다. 추출 품질 사례에서 별도 확인한다.

## 검색·법령

후보는 배치당 3개, 문헌 근거는 후보당 최대 2개로 시작한다. 전체 후보 수를 3개로 잘라 버리지 않는다.
여러 배치 결과는 scenario_id로 합치고 근거를 중복 제거한다. MVP는 평가표당 같은 scenario_id 한 행으로 합친다.
기기 인스턴스별 다른 등급은 이번 계약에 포함하지 않는다. 서로 상충하는 조치 근거는 unknown으로 보존한다.
문헌 source_refs는 해당 카탈로그 시나리오에 등록된 문서·쪽 조합만 전달한다.
등록 후보에 입력 근거가 있지만 문헌이 없으면 retrieval_status=no_evidence로 유지하며 평가를 계속할 수 있다.
법령은 법령 원문·시행일·적용 조건을 검수한 매핑만 사용한다. 법령 확인 실패 때문에 정상 위험행 전체를 폐기하지 않는다.

기본 legal_registry.json은 빈 배열이므로 legal_refs=[]다. 검수 자료 확보 후 검색·통합 담당이 등록한다.
등록 형식: legal_id, url, scenario_ids. 운영 매핑에는 시행일·검수 출처·적용 조건도 보존하고 조회 시 확인한다.
validate(..., legal_registry=...)는 신뢰된 등록 자료와 ID/URL/시나리오 연결을 대조한다. 법률적 적용성 검증 도구가 아니다.
검사 중 example.invalid 법령은 합성 등록 테스트 전용이며 실제 문서에 인용하지 않는다.

## 계산·처리 상태

assessment_mode=input_based, base_policy_version=CATALOG-MVP-1.1,
decision_policy_version=CATALOG-MVP-1.1-AUTO-1.0.
사용자 추가 입력·현재 조치 확인을 요구하지 않는다. questions=[]이며 모델은 등급을 생성하지 않는다.
서버는 카탈로그 S와 기존 MATRIX를 재사용한다. 빈도×강도 계산이나 빈도 입력은 없다.
핵심 조치 중 하나라도 supported가 아니면 C3, 핵심은 모두 supported이고 보완이 부족하면 C2, 전체가 supported이면 C1.
unknown은 사실 미실시가 아니며 계산에서만 미충족으로 취급한다. 계획으로 현재 위험도를 낮추지 않는다.

| 상황 | result_status | items |
| --- | --- | --- |
| 유효 행 있음·미매칭 없음 | complete | 상/중/하 행 |
| 유효 행 있음·일부 미매칭 | partial | 유효한 행만 유지 |
| 유효 행 없음 | no_supported_result | 빈 배열 |
| 입력/모델/계약 오류 | 성공 결과를 반환하지 않음 | 기존 오류 경로 |

retrieval.unmatched와 analysis.unmatched_risks를 합쳐 보존한다. 검색 후보의 단순 기각은 미매칭 위험과 구별한다.
no_evidence는 문헌 검색 상태, unknown은 조치 근거 상태, result_status는 전체 처리 상태다. 서로 대체하지 않는다.
개별 행 status=estimated_from_input이며 화면 등급은 상/중/하만 표시한다.

## 기존 서비스 매핑

AssessmentCore는 통합 검사용 핵심 결과다. 서비스는 기존 catalog_state JSON과 상세 응답에 다음을 연결한다.

| 저장 내용 | 원천 |
| --- | --- |
| assessment_mode·정책 버전·result_status·unmatched_risks | AssessmentCore와 카탈로그 버전 |
| 현재 등급·S·C·행 상태 | AssessmentCore.items |
| 위험 설명·근거·가정 | 검증된 AnalysisBundle |
| 현재 조치 | supported 입력 근거만. 없으면 “입력에서 확인된 조치 없음” |
| 개선대책 | 카탈로그 plan_text. 현재 시행 사실로 저장하지 않음 |
| 문헌·법령 참조 | 검증된 RetrievalBundle |
| input_revision·모델/프롬프트/자료 버전 | 기존 실행 메타데이터 |

기존 `backend/domain/risk_policy.py`의 MATRIX를 import한다. 이 묶음의 reference/risk_policy.py는 독립 실행 검사용 원본 스냅샷이며 서비스에서 import하지 않는다.
사용자 확인을 뜻하는 answered/controls_reviewed를 true로 위조하지 않는다. input_based 분기에서 별도 계산하고 저장·확정 게이트도 같은 모드로 연결한다.
기존 수동 평가와 과거 저장 결과는 당시 정책으로 조회한다. 입력 revision이 달라진 늦은 결과로 덮어쓰지 않는다.
생성·저장·재조회·화면·PDF의 grade/정책/근거가 일치하면 통합 완료다.


## 일반 평가표 위험도 계약 — FOOD-3LEVEL-1.2 (2026-11-21)

정책 기준: [위험도 합의 문서](../../../docs/implementation/risk-development-agreement.md). 이 절은 input_based가 아닌 일반 평가표(`catalog_rls_v1`·`catalog_v1`·`catalog_ai_v1`)의 입출력이다.
input_based(이 v1 묶음)는 `base_policy_version=CATALOG-MVP-1.1`을 유지한다(검사 코드가 1.1 MATRIX·카탈로그를 고정). 1.2 전환은 v2 계약에서 정한다.

| 단계 | 입력 | 결과·저장 |
| --- | --- | --- |
| 생성 `POST /evals` | 작업 설명·전사문·등록 기기 | 행별 `catalog_state.scenario`(1.2 시나리오, `policy_version`), `links`(action_id → control_id), 체크 0개 기준 `current_result`·`projected_result` |
| 조회 `GET /evals/{no}` | — | 행 `policy_version`, 행 `signal`(현재)·`after`(예상), 조치별 `control`(`control_id`·`critical`·`status`·`message`), `catalog.current_result`·`projected_result` |
| 저장 `PUT /evals/{no}` | 조치 `id`(action_id)·`checked`·`text`, 직접 입력은 `id=null` | 서버가 저장된 `links`로 control_id를 찾아 재계산. 결과와 체크를 같은 트랜잭션에 저장, `risk_event(kind=calculation)` 기록 |
| 확인 대기 `POST /evals/{no}/pending-rows` | `scenario_id`, `decision`=add/dismiss | add: 1.2 기준 행 생성(체크 0개 계산) |

- 계산 대상: 체크했고, 그 행의 `links`에 있고, 행 시나리오의 기준 조치 ID인 것만. 다른 행·시나리오 ID, 미확정 추천(`control_id=null`), 직접 입력은 저장만 한다.
- 현재 = `evaluate(scenario, 현재 ID)`, 예상 = `evaluate(scenario, 현재 ID ∪ 개선 ID)`. 같은 ID는 한 번만 센다. 예상은 계획 이행을 가정한 값이다.
- `current_result`·`projected_result` 필드: `policy_version`, `grade`(상/중/하), `signal`(R/Y/G/N), `severity`, `control_band`(1 전체·2 핵심만·3 핵심 미충족), `applied_control_ids`, `missing_critical_ids`, `missing_supplementary_ids`, `reason`(반영 ID·남은 조치·등급 유지 이유).
- 정책 버전: 평가표의 모든 행은 같은 `policy_version`을 쓴다. 저장된 1.1 행은 1.1로 재계산하고, 1.2로 바꾸지 않는다. 지원하지 않는 버전은 409.
- 시나리오 미연결·근거 부족 카드는 행을 만들지 않고 `risk_law.unmatched`로 보존한다(판단 필요·검토 흐름).

## 담당자 확정 기준 (2026-11-19 팀 결정)

`input_based`의 AI 출력과 계산 결과는 모두 초안이다. `complete`는 입력 처리 상태다.
탐지·보유 정보만 있으면 검색 후보를 보존하고 작업 미확인으로 표시한다. 해당 작업을 뒷받침하는 텍스트·전사가 있을 때만 추정 등급 행을 만든다.
현재 조치 근거가 부족하면 unknown으로 남긴다. 동일 등급이 나와도 조치 미실시 사실로 표시하지 않는다.
담당자가 실제 작업 여부와 원문 근거를 행별로 검토하고 명시적으로 확정해야 한다.
AssessmentCore.review_candidates에는 등급 행과 별도로 담당자가 검토할 후보를 담는다.
후보는 scenario_id와 reason(work_unconfirmed 또는 input_denies_work)을 가지며, 후보가 없으면 빈 배열을 반환한다.
기기에서 찾은 후보의 작업 근거가 없으면 work_unconfirmed, 실제 작업을 하지 않는다고 입력에 명시하면 input_denies_work다.
input_denies_work는 검토 사유다. 담당자가 비적용으로 결정하면 제외를 확정한다.
담당자가 후보를 확인해 재계산하거나 비적용으로 명시적으로 제외하기 전까지 평가표 확정을 보류한다.
result_status는 계산된 행과 미매칭 상태를 나타낸다. 확정 가능 여부는 담당자 검토 이력으로 확인한다.
관련 논의는 [공통 계약 PR #31](https://github.com/chaechae001/SafeT/pull/31)에 기록한다.
확정 API 연결 시 인증·소유권·revision 및 사용자 검토 기록을 서버에서 검사한다.
모델 결과, 추정 등급, 처리 완료 상태로 검토 기록을 생성하지 않는다.
기존 수동 경로의 확인·잠금 규칙은 유지한다.
