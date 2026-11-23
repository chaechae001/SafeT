# UX-018 결과 · 2026-11-22

## 변경

| 영역 | 파일 | 내용 |
|---|---|---|
| 회원 탈퇴 | `backend/services/auth.py`, `schemas/auth.py`, `routers/auth.py` | `POST /auth/withdraw {password}`. 비밀번호를 다시 확인한 뒤 처리한다. 처리 내용은 다음과 같다(DB 구조 변경 없음). ① 로그인 불가 표식 `pw='WITHDRAWN'` ② 이름 삭제 ③ 기존 토큰 종료 ④ 사업장 사용 중지 ⑤ 공유 링크 중지 ⑥ 평가 기록은 보존. 비밀번호 재설정으로 되살릴 수 없다. 틀린 비밀번호는 400 `PASSWORD_MISMATCH`(401이면 화면이 로그인 만료로 처리하므로 피함) |
| 회원 탈퇴 화면 | `frontend/pages/workplace.html`, `js/account.js`, `css/workplace.css`, `js/login.js` | 사업장 관리 목록 아래 `회원 탈퇴` → 확인 창(알림 4줄 + 비밀번호). 완료하면 `login.html?withdrawn=1` 안내 |
| 배포 설정 | `frontend/js/config.js`, 10개 페이지 | `api.js` 앞에서 로드. 배포 서버는 이 파일에만 `window.SAFET_API_BASE`를 적는다 |
| 사업장에도 저장 | `schemas/assessment.py`, `services/assessment.py`, `pages/write.html`, `js/assessment-write.js` | `save_machines_to_workplace: true`이면 추가 기기를 `workplace_machine`에도 넣는다(변경 확인 뒤 같은 트랜잭션) |
| 03 안내 위치 | `js/assessment-write.js`, `css/field.css` | 등록 기기 설명은 등록 기기 상자 아래에 둔다. '매장에 있는 것만 체크' 안내는 찾은 기기가 있을 때만 보인다 |
| 확인 대기 N건 | `services/evaluations.py`, `schemas/evaluation.py`, `js/home.js` | `GET /evals`에 `pending_count`(`authoring_snapshot.rls_pending` 길이) 추가. 작성 중 카드에 표시 |

## 검증
- 백엔드:
  - `tests/test_ux018_account.py` 3개 통과(탈퇴 실패·성공·재설정 차단, 확인 대기 수)
  - `tests/test_ux017_machines.py` 5개 통과(사업장 저장 포함)
- 화면: UX-019 회귀 실행에서 UX-017 화면 검사 20/20, 생성 → 확정 → 서명 → 다운로드 흐름 통과
- 미확인: 탈퇴 창을 실제로 눌러 탈퇴하는 화면 흐름. 테스트 계정 보존을 위해 화면에서 실행하지 않았고, 서버 테스트로만 확인했다.
