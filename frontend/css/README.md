# 스타일

공통 스타일은 `common.css`, 화면 전용 스타일은 `basic.css`처럼 화면 이름으로 구분합니다.

- 공통 색상·글꼴·버튼 변경은 관련 작업자와 먼저 조율합니다.
- 화면 전용 스타일은 해당 화면의 최상위 클래스 아래에 적용합니다.
- 실제 CSS 파일은 화면 뼈대 구현 때 추가합니다.

## 추가한 스타일 (2026-11-16)

- `common.css`: 색상·글꼴 토큰, 버튼·입력·카드·신호등·확인 창·진행률, view 전환(`.view.is-active`) 같은 공통 요소.
- 신호등은 `data-signal="R|Y|G|N"`(공통코드 RISK_GRADE), 평가 상태는 `data-status="W|C|S|A"`(EVAL_STATUS)로 표시합니다.
- 값의 출처는 `src--ai`(AI 추천·판단), `src--manual`(직접 추가), `src--bulk`(일괄 지정)으로 구분합니다.
- 화면 전용 파일: `auth.css`, `workplace.css`, `home.css`, `field.css`, `draft.css`, `risk.css`(위험 상세 계열), `bulk-assign.css`, `result.css`, `sign.css`, `share.css`.
- 화면 전용 스타일은 view 섹션의 클래스(예: `.view.risk`) 아래에 적용됩니다.
