## 목표
입력에 맞는 위험 시나리오와 근거를 찾고, 모델 분석을 검증하여 위험도·평가표·저장 결과로 연결한다.

## Input → Output
- 검색: `InputBundle + catalog_snapshot → RetrievalBundle`.
- 후처리: `InputBundle + RetrievalBundle + AnalysisBundle → 평가표 데이터`.
- 함수: retrieve_evidence(context, catalog_snapshot), compose_assessment(context, retrieval_bundle, analysis_bundle, catalog_snapshot). 검증·계산은 조립 함수 내부 단계다.

## 검색 구현
1. 기존 RAG 인덱스와 기기→위험코드→시나리오 관계를 재사용한다.
2. 원문·기기 ID를 동의어로 정규화하고, 기기 없는 청소·이동 작업도 조회한다.
3. 명시적 비적용·중복을 정리한다. 불명확한 작업을 실제 수행으로 확정하지 않는다.
4. 카탈로그 조치·문헌 페이지·검수된 법령을 연결한다.
5. 후보 한 배치 3개, 후보별 근거 최대 2개로 시작한다. 직접 관련된 추가 위험은 후속 배치에 보존한다.
6. `retrieval.json`과 미매칭 목록을 반환한다.

## 분석 검증·계산·조립
1. 추출 담당이 반환한 `analysis.json`의 Schema·시나리오/조치 소속·media_id를 검사한다.
2. supported/not_effective의 근거 누락, 잘못된 ID, 중복을 거절한다.
3. 누락 조치는 unknown으로 정규화한다. unknown을 실제 미실시로 바꾸지 않는다.
4. 기존 카탈로그 S와 MATRIX를 재사용해 상/중/하를 계산한다.
5. 계획은 현재 등급을 바꾸지 않는다. 예상 위험도는 별도 계산한다.
6. 조치·출처·법령·짧은 설명을 템플릿으로 조립한다.
7. 기존 API·DB·화면·PDF를 연결하여 생성/저장/재조회 결과를 맞춘다.

## 편집 파일
- `ai/assessment_authoring/retrieval_adapter.py`, `mappings/`
- `ai/assessment_authoring/analysis_validator.py`
- `ai/assessment_authoring/assessment_composer.py`
- `ai/assessment_authoring/tests/test_retrieval.py`, `test_composer.py`
- 공통 `schemas/`, 골든 `examples/`, `validate.py`
- 통합 호출부: `backend/services/catalog_ai.py`, `catalog_risk.py`, `assessment.py`
- 계산 연결: `backend/domain/risk_policy.py`
- 이후 UI/UX: `frontend/js/assessment-write.js`, `draft.js`, `catalog-ai.js`, `assessment-result.js`

## 통합 규칙
공통 서비스 파일의 직접 편집자는 한 명으로 유지한다. 입력·추출 담당은 독립 모듈과 연결 방법을 전달한다.
현재 API 형태·DB JSON 저장을 우선 유지한다. 모델 원문이나 클라이언트 체크값으로 등급을 덮어쓰지 않는다.
새 모드 `input_based`, 기본 정책 `CATALOG-MVP-1.1`, 결정 정책 `CATALOG-MVP-1.1-AUTO-1.0`을 기록한다.
사용자 확인 플래그를 가짜로 true로 채우지 않는다. 과거 문서는 당시 기준으로 조회한다.

## 전달 파일
검색 결과·미매칭 예시, 근거 매핑, 통합 테스트 결과, 현재/예상 결과 예시, 실행·설정 안내.

## 완료 기준
검색 ID·출처 유효, 잘못된 모델 근거 차단, S/C 9조합 일치, 미확인 보존, 계획과 현재 분리, 생성/저장/조회/PDF 일치, 소유권·revision·과거 문서 회귀 통과.

## 공통 계약 보강

INTERFACES.md의 AssessmentCore·partial·no_supported_result·legal_registry 규칙을 따른다.
잘못된 supported/ID/인용은 오류로 반환하며 누락된 조치만 unknown으로 정규화한다.
프로덕션은 backend/domain/risk_policy.py의 MATRIX를 import한다. reference의 스냅샷은 독립 검사 전용이다.

## 시작
검색은 고정 `input.json`, 검증·계산은 고정 `analysis.json`으로 시작한다. 실제 탐지와 LLM이 완성될 때까지 기다리지 않는다.

## 개발 AI 작업 지시
```text
기존 RAG와 risk_policy를 재사용해 검색·분석 검증·결과 조립을 구현해줘.
retrieve_evidence는 retrieval.schema.json, 모델 분석은 analysis.schema.json을 기준으로 검사해라.
등록 ID·근거 소속·중복·unknown을 처리하고 기존 MATRIX로 상/중/하를 계산해라.
법령·출처를 생성하지 말고 현재/계획을 분리해라.
고정 input/retrieval/analysis로 먼저 검사한 뒤 독립 입력·추출 어댑터를 서비스에 연결해라.
입력·탐지·추출 담당자의 모듈 본문은 수정하지 마라.
```

