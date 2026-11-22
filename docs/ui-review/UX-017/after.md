# UX-017 결과 · 2026-11-22

## 조건
- 기준: 커밋 `00b571a`(브랜치 `ux/screen-review-261122`), 로컬 미커밋 변경.
- 실행: 화면 `localhost:8000`(SafeT-pr 작업 트리), API `8001`, `catalog_rls_v1`, 로컬 위험요인·법령 검색 서버 `8020`. 외부 AI 모델 호출 없음.
- DB: UX 검토 전용 `safet_ux_review_261121`(합성 계정). 테스트 계정 `ux-new@test.invalid`.
- 캡처: Edge · 390×844 · 배율 2. 수정 전은 HEAD 프런트를 같은 주소로 대신 응답해 같은 계정·데이터로 촬영.
  - 수정 전: `before/`
  - 수정 후: `after/`
- `*.png`는 `.gitignore` 대상이라 저장소에 올라가지 않습니다.

## 변경 파일

| 파일 | 내용 |
|---|---|
| `frontend/pages/login.html`, `frontend/css/auth.css` | 개인정보 창 4가지 고지(`#terms` 안으로 스타일 한정) |
| `frontend/pages/result.html` | 설계 주석: 서명하기·결과 공유 하단 버튼 |
| `frontend/pages/write.html`, `frontend/js/assessment-write.js`, `frontend/css/field.css` | 03 기기 직접 추가 창(`#eq-add`) |
| `frontend/js/home.js` | 카드에 `위험 항목 N건` |
| `backend/schemas/assessment.py`, `backend/services/assessment.py` | `add_machine_codes`·`add_custom_machines` |
| `backend/schemas/evaluation.py`, `backend/services/evaluations.py` | `item_count` |
| `backend/tests/test_ux017_machines.py` | 신규 테스트 4개 |
| `backend/README.md` | 새 칸 설명 |

### 03 기기 직접 추가 창(`#eq-add`) 동작
- 이름 입력칸을 맨 위에 둡니다. 업종 기기 목록이 길어도 입력칸이 밀리지 않습니다.
- 그 아래 업종 기기 칩(`aria-pressed`)에서 고릅니다.
- 추가 결과는 알림 대신 창 안의 상태 문구로 보여 줍니다.
- 고른 기기는 화면에 '이번 평가에 추가한 기기' 칩으로 보이고, ×를 눌러 뺄 수 있습니다.
- 작성 중 로그인이 만료되면 추가한 기기도 복구합니다.

## 검증

| 검사 | 결과 |
|---|---|
| 화면(수정 후) | 20/20 PASS. 항목은 `after/result.json` |
| 화면(수정 전) | 6/11. 고지 4가지·항목 수가 없는 것은 수정 전 상태라 예상한 결과 |
| 백엔드 | `tests`+`unit_tests` 275 passed(기존 271 + 신규 4, 격리 `_test` DB) |
| 지침 CPU 자체 검사 | 3/3 통과 |
| contracts JSON | 47개 읽기 통과 |
| 사업장 수정 브라우저 검사 | `WORKPLACE_EDIT_INPUT_RECOVERY_PASS` |

### 직접 추가한 기기가 계산에 반영되는지
1713 평가표로 확인했습니다.
- 등록 기기: 채소절단기
- 직접 추가: 튀김기(업종 기기), 시험용 제빙기(이름 입력)
- 결과: 확인 대기 항목에 '튀김기' 기준 "작업 환경에 적합한 소화기(K급) 미비치"가 생겼습니다. 추가한 기기가 위험요인 검색에 들어간 것입니다.
- '시험용 제빙기'는 맞는 위험 카드가 없어 항목이 생기지 않았습니다.

## 검수 중 생긴 데이터
UX DB `ux-new` 계정에 작성 중 평가표 1713·1714가 생겼습니다. 둘 다 시험 생성분입니다.

## 미확인
- 실제 휴대폰: 터치, 키보드가 창을 가리는지, 화면 낭독기
- 배포 서버 반영
- 개인정보 문구의 법적 충분성(팀·법무 확인 필요)
- 보유 기간 "3년"의 근거는 산업안전보건법령의 위험성평가 기록 보존 규정으로 이해했습니다. 법무 확인 때 함께 확인해야 합니다.
