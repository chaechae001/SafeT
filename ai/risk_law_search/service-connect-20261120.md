# 위험요인·법령 검색 모듈 → 사용자 평가표 화면 연결 기록 (2026-11-20)

> 상태: 개발 연결. 카드→시나리오 연결표와 대책→기준 조치 연결표는 자동 초안이며 검토 팀원 검토 전이다. 법령은 자동 검색 후보이며 적용 판단은 작성자가 한다.

## 1. 목표 흐름

1. 작성자가 작업 설명(글·음성 전사문)을 넣고 평가표를 만든다.
2. 위험요인마다 현재 대책 3개·개선 대책 3개를 **AI 추천**으로 보여 준다.
3. 처음에는 체크 0개 기준으로 현재·예상 위험도를 계산한다(같은 값).
4. 작성자가 추천을 체크하거나 행 추가로 직접 적는다.
5. 저장하면 체크·입력 내용으로 현재·예상 위험도를 다시 계산해 저장한다.

## 2. 연결 방식

기존 DB 기준 평가(`catalog_v1`)의 '입력 글에서 시나리오 찾기(문자열 포함)'만 우리 모듈로 바꾼 생성 모드 `catalog_rls_v1`을 추가했다. 저장·재계산·확정·PDF는 기존 코드를 그대로 쓴다.

```
작성 화면 → POST /evals (catalog_rls_v1)
  → services/risk_law.py → 모듈 서버 POST /api/analyze (SAFET_RISK_LAW_URL)
     위험 카드 → 시나리오(card_scenario_map) · 추천 대책 3+3(대책별 기준 조치 연결) · 법령 후보(C)
  → 시나리오별 한 행(eval_dtl) · 추천 대책(eval_action, ai_yn=Y)
     catalog_state: scenario · links(action_no→기준 조치 ID) · risk_law(참고) · 위험도 결과
  → 저장(PUT /evals/{no}) → catalog_risk.recalculate → 현재·예상 위험도 재계산 · risk_event 기록
```

데이터 설계 문서(`docs/chroma/risk-card-data-model-team-guide.md`)와의 대응

| 설계 문서 | 이번 연결 |
|---|---|
| knowledge_card · hazard_card | 카드 116개 · `card_scenario_map.json` |
| card_control · hazard_control | `measure_control_map.json`(신규) |
| current_control · improvement_action | `eval_action` C · P |
| assessment_item_legal(적용 미확인) | `catalog_state.risk_law.law` |
| risk_evaluation(current·projected) | `catalog_state.current_result·projected_result`, `risk_event` |

## 3. 바꾼 파일

| 파일 | 내용 |
|---|---|
| `backend/services/risk_law.py` (신규) | 모듈 호출, 응답 → 평가표 행 변환(같은 시나리오는 한 행), 대책→기준 조치 연결 |
| `backend/services/catalog_risk.py` | `catalog_rls_v1` 추가. 생성 시 체크 0개로 현재·예상 계산, 저장 시 재계산. 대책별 반영 여부를 화면에 전달 |
| `backend/services/assessment.py` | 행 생성 시 참고 정보 전달 |
| `backend/run_local.py` | `--risk-law` 실행 옵션(검색 서버 응답 확인) |
| `frontend/pages/draft.html`, `frontend/js/draft.js` | 'AI 추천' 표시, 대책별 '위험도 반영/계산 제외', 'AI 검색 근거·법령 후보 보기(작성자 확인)' |
| `frontend/js/assessment-write.js`, `frontend/css/common.css` | 초안 생성 대기 화면: 0%에 멈춘 원형·빈 진행 막대 대신 회전 표시와 경과 시간. 실제 진행률을 알 수 없어 단계·막대는 표시하지 않음(입력 1문장 + 기기 18개 기준 검색 약 16초) |
| `ai/risk_law_search/control_map.py` (신규), `measure_control_map.json` (신규) | 카드 대책 2,492개 → 기준 조치 자동 후보. 기본은 검토 완료만 계산 반영 |
| `ai/risk_law_search/engine.py` | 추천 대책에 기준 조치 연결(`control`) 추가. 분석 시 위험도 기록 DB 쓰기 제거 |
| `ai/risk_law_search/server.py` | 위험도 계산·기록 API(`/api/risk-grade`·`/api/risk-draft`·`/api/risk-scenarios`)를 `--risk-test`에서만 열기, `--count-auto-controls`(시험용) |
| 테스트 | `backend/unit_tests/test_risk_law.py`(7개), `backend/tests/test_risk_law_flow.py`(DB), 모듈 테스트 1개 |

## 4. 확인 필요 (팀 결정·검토)

1. **계산 시점(2026-11-21 FOOD-3LEVEL-1.2 적용으로 확정)**: 생성 시 체크 0개 기준으로 현재·예상을 계산하고 저장할 때마다 다시 계산한다. '목록 전체 확인' 체크는 확정 조건이다. [합의 문서](../../docs/implementation/risk-development-agreement.md#신규-평가표-정책--food-3level-12-2026-11-21).
2. **대책→기준 조치 자동 연결 품질이 낮다(2026-11-21: 추천을 기준 조치로 직접 구성해 해소)**: 이제 체크 항목은 1.2 기준 조치 자체라 연결표 없이 계산된다. 카드 대책 문장은 검토 완료 연결이면 해당 기준 조치를 앞에 두고, 나머지는 계산 제외로 저장한다. 이전 기록: 점수 0.45 이상에서도 '운전 중 스마트폰 사용 금지 → 운전 전 점검' 같은 오연결이 있다. 그래서 기본값은 검토 완료(`confirmed`)만 계산에 반영한다. 현재 확정 0건이라 **검토 전에는 체크해도 위험도가 바뀌지 않는다**. 검토 팀원이 `measure_control_map.json`의 `confirmed`를 채워야 한다.
3. **카드→시나리오 연결 검토**: 예) '식용유에 착화되어 화재'가 FIRE가 아니라 FRY(기름 튐)로 연결된다. `card_scenario_map.json` 확정 0건.
4. **직접 추가 대책은 계산 제외**: 합의 문서·설계 문서 기준. 입력 내용까지 계산에 넣으려면 자동 매칭 규칙을 팀이 정해야 한다(오매칭 시 부당 하향 위험).
5. **추천 3개 한계(2026-11-21 해소)**: 현재·개선 각 3개를 먼저 보이고, 판정에 필요한 나머지 기준 조치는 '남은 조치 보기'에서 선택한다. 이전 기록: 핵심 조치가 3~5개라 추천 3개를 모두 체크해도 위험도가 내려가지 않을 수 있었다.
6. **정책 버전(2026-11-21)**: 신규 평가표·내부 검토 화면 모두 FOOD-3LEVEL-1.2와 같은 카탈로그 파일(`catalog-food-3level-1.2.json`)을 쓴다. 기존 1.1 평가표는 저장 당시 정책으로 계속 계산한다.
7. **모듈 서버 인증 없음**: 백엔드만 접근하는 내부 주소로 둔다.
8. **등록 기기도 검색어로 사용(2026-11-21 변경)**: 등록 기기는 검색어로 보내되, 공통 계약('보유 정보는 작업 근거가 아님')에 따라 기기에서만 나온 위험은 행이 아닌 '확인 대기'에 둔다. 담당자가 실제 작업으로 확인해 추가하면 행이 되고(체크 0개 기준 1.2 등급), 하지 않는 작업은 제외한다. 확인 대기가 남으면 확정할 수 없다.

## 5. 검사

- 백엔드 단위 테스트: `python -m pytest backend/unit_tests -q`(브라우저 검사 제외) 81개 통과(신규 7개 포함).
- DB 흐름 테스트(`backend/tests/test_risk_law_flow.py`): 테스트 DB 안전장치 조건이 없어 **실행하지 않음(건너뜀)**.
- 실제 모듈 서버 연결: '칼 튀김기 선반 바닥' → 행 7개(KNIFE·KNIFE_STORAGE·FRY·FIRE·LADDER·STORAGE·ENV), '회의를 합니다' → 행 없음(422 안내).
- 모듈 테스트: 34개 중 23개 통과, 10개 패키지 없어 건너뜀, 1개 실패(4-6).
- 전체 실행(`run_local.py --risk-law --migrate`)으로 로컬 DB에서 로그인 → 평가표 생성(201) → 작성 화면 조회(200)를 서버 기록으로 확인했다. 저장·확정과 화면 표시는 자동 검사하지 않았다. JS 구문 검사 도구는 이 PC에 없다.
- CPU 자체 검사 3개 통과.

## 6. 다음 작업

1. 테스트 DB로 `test_risk_law_flow.py`와 화면 흐름(생성 → 체크 → 저장 → 재조회 → 확정 → PDF)을 확인한다.
2. 검토 팀원이 대책→기준 조치, 카드→시나리오 연결표를 검토한다.
3. 합의 문서에 이 모드의 계산 시점·직접 추가 처리 규칙을 반영한다.
