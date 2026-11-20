# 위험도 작업 인계 (2026-11-20)

> 대상: 위험도(현재·예상 등급) 작업을 이어받는 담당. 이 모듈은 확인용 독립 모듈이며 서비스(평가표 저장·확정)와 아직 연결되지 않았다.
> 기준 문서: [위험도 개발 기준 — 최종 합의](../../docs/implementation/risk-development-agreement.md), [공통 계약](../../contracts/assessment_authoring/v1/INTERFACES.md), 공통 계산 [`backend/domain/risk_policy.py`](../../backend/domain/risk_policy.py)(CATALOG-MVP-1.1).

## 1. 지금 상태 요약

| 단계 | 상태 |
|---|---|
| 입력 → 위험요인 후보 | 됨. 문장·낱말·절·등록 기기 단위로 위험사례 카드 1~3개 |
| 위험요인 → 법령 후보 | 됨. 기본 C(KURE 검색 후보 + 위험유형 주제 확인). [비교 통계](abc-stats-20261120.md) |
| 위험요인 → 위험도 시나리오 | **자동 후보만 있음.** `card_scenario_map.json` 확정(confirmed) 0/105 |
| 조치 선택 → 시나리오 조치 ID | **없음.** 화면 선택지가 카드 대책 문장이라 계산 기준의 조치 ID와 다르다 |
| 등급 계산 | **이 모듈에서는 하지 않는다.** 합의대로 공통 서버 모듈이 계산한다 |

## 2. 이 모듈이 넘겨주는 것 (`POST /api/analyze`)

위험요인(`units[].risks[]`)마다:

| 필드 | 내용 |
|---|---|
| `card_id`, `title`, `risk_type`, `text` | 위험사례 카드 |
| `law`, `law_basis` | C 법령 1개(없으면 `null` + '담당자 확인 필요'). 후보이며 적용 미확인 |
| `law_card`, `law_alt`, `law_alt_topic` | 비교용 A·B·C 후보 |
| `current_options`, `improvement_options` | 카드 대책 문장 선택지 각 3개(`id` 예: `OPS-04-H2:M1`, 처음엔 모두 `selected: false`) |
| `scenario` | 위험도 시나리오 후보(아래) |

`scenario` 예시('식칼이 떨어짐'):

```json
{"status": "auto", "message": "자동 후보 · 검토 전",
 "scenario_id": "KNIFE", "title": "날에 손이 접촉해 베임", "policy_version": "CATALOG-MVP-1.1",
 "severity": 2, "severity_reason": "...",
 "controls": [{"id": "KNIFE-C1", "critical": true, "current_text": "...", "plan_text": "..."}],
 "candidates": [{"scenario_id": "KNIFE", "score": 0.44}, {"scenario_id": "KNIFE_STORAGE", "score": 0.14}]}
```

- `status`: `confirmed`(담당자 확인) · `auto`(자동 후보·검토 전) · `auto_weak`(점수 0.2 미만) · `no_scenario`(담당자가 '없음'으로 확인) · `unmapped`/`invalid`
- `scenario` 객체는 `risk_policy.evaluate()`에 그대로 넣을 수 있다(테스트로 확인).

```python
# backend 안에서(기존 services/catalog_risk.py와 같은 방식)
from domain.risk_policy import evaluate
s = risk["scenario"]
evaluate(s, selected_ids, answered=controls_reviewed)
# 확인 전(answered=False) → grade None, signal 'N'(판단 필요)
```

## 3. 위험도 담당이 할 일 (권장 순서)

1. **카드 → 시나리오 확정**: [`card_scenario_map.json`](card_scenario_map.json)의 `confirmed`에 시나리오 ID 또는 `"none"`을 적는다. 피해 수준이 그대로 등급에 들어가므로 자동 후보를 그대로 쓰지 않는다.
   - 다시 계산(확정 보존): `python -m ai.risk_law_search.scenario_map --update`
   - 먼저 볼 카드: 약한 후보 2개(FOOD-05-H3 → RICE, FOOD-11-H2 → TRANS)와 눈에 띄는 오연결(OPS-04-H4 가공기계 누전 → CUT, OPS-07-H4 세척기 누전 → WASH, EDU-H07 소화기 비치 → GAS). 감전 카드는 ELECT가 맞아 보인다.
2. **조치 선택지를 시나리오 조치로 맞추기**: `evaluate()`는 시나리오 `controls[].id` 선택을 받는다. 지금 화면의 선택지는 카드 대책 문장이다. 둘 중 하나를 정한다.
   - (권장) 위험도 계산용 선택지는 시나리오 `controls`(`current_text`/`plan_text`)로 보여 주고, 카드 대책은 참고 문구로 둔다. 계산 기준과 화면이 일치한다.
   - 카드 대책 → 조치 ID 매핑표를 만든다. 문장 수가 많아 검수 부담이 크다.
3. **합의 규칙 적용**(합의 문서 그대로)
   - 작업 해당·현재 조치 목록 전체 확인 전에는 `answered=False` → N(판단 필요), 확정 차단
   - 현재 조치는 자동 체크하지 않는다. 미선택은 확인 후에만 '미실시'
   - 예상 위험도 = 현재 조치 + 선택한 개선 대책이 이행·작동한다는 가정. 실제 개선 완료로 표시하지 않는다
   - 직접 추가 대책은 기준 ID가 없으므로 자동 하향하지 않는다
   - 정책 버전·현재 결과·예상 결과를 기록한다
4. **같은 시나리오 합치기**: 계약상 MVP는 평가표당 같은 `scenario_id`를 한 행으로 합친다. 이 모듈은 카드 단위라 여러 카드가 같은 시나리오(예: 바닥 카드 3개 → ENV)로 나온다.
5. **법령 연결 정리**: 계약상 평가표 `legal_refs`에는 검수된 법령만 넣는다. 이 모듈의 C 법령은 후보로만 표시한다. #45(`ai/legal_review`)와의 역할은 Issue에서 정한다.

제외(합의 문서): PDF 37–41쪽 부록(후속업무 관리, 실제 조치 결과·재산정, 지난 평가 가져오기).

## 4. 확인 방법

```
python -m ai.risk_law_search.server --mode keyword          # 기본 법령 C, 시나리오 후보 표시
python -m unittest discover -s ai/risk_law_search/tests -t .
```

- 화면: 위험요인마다 '위험도 시나리오: KNIFE · 날에 손이 접촉해 베임 · 피해 수준 S2 · 자동 후보 · 검토 전'이 보인다. '조치 기준·다른 후보'를 펼치면 핵심·보완 조치가 나온다.
- 테스트 `test_risks_carry_scenario_for_risk_grading`: 시나리오 후보를 `risk_policy.evaluate()`에 넣어 확인 전 N, 확인 후 계산됨을 검사한다.

## 5. 관련 파일

| 파일 | 역할 |
|---|---|
| `scenario_map.py` | 카드 → 시나리오 후보 생성(`build`)과 조회(`ScenarioLinker`) |
| `card_scenario_map.json` | 카드 105개의 시나리오 후보 3개 + 담당자 확정 칸(검토 전 초안) |
| `engine.py` | `analyze()`가 위험요인에 `law`(C)·`scenario`를 붙인다 |
| `law_kure.py` | C 법령의 KURE 검색 |
| `server.py` | `--law c`(기본) / `a`, `--build-alt-index` |
| `contracts/catalog_risk/catalog.json` | 시나리오 26개(피해 수준·조치 기준, 수정하지 않음) |

## 6. 주의

- 시나리오 후보와 정답 세트는 AI 보조 초안이며 담당자 검토 전이다. 미평가·정보 부족을 낮은 위험으로 처리하지 않는다.
- 최종 안전 판단은 담당자가 한다.
