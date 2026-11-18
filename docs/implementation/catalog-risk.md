# DB 기준 위험도 계산

최종 개발 기준은 [2026-11-17 합의서](risk-development-agreement.md)를 따른다.

- 입력 키워드로 DB 위험 후보를 찾고 사용자가 작업 해당 여부·조치 목록 전체를 확인한다.
- 현재 조치/조치 없음과 목록 확인을 저장하면 현재 위험도를 계산한다.
- 개선대책 선택 후 저장하면 이행·효과를 가정한 예상 위험도를 같은 함수로 계산한다.
- 현재 결과와 예상 결과를 따로 저장하며 자유 입력 대책은 자동 감경하지 않는다.
- 미확인 정보는 N, 임시저장 허용·확정 차단이다.
- 사망·영구장해 사고 경로가 남으면 필요한 조치가 모두 있어도 상이다.
- PDF 37–41쪽 부록(실제 이행·재산정·후속업무·지난 평가 가져오기)은 제외한다.

정책 버전: CATALOG-MVP-1.1. 기존 기준을 덮어쓰지 않고 새 버전으로 적재한다.

## 실행·검사

개인/격리 DB에서 `python backend/run_local.py --catalog --migrate` 실행.
정책 검사: `python -m pytest backend/unit_tests/test_catalog_policy.py -q`.
격리 *_test DB에서 API 검사: `python -m pytest backend/tests -q`.
화면 검사: `python backend/unit_tests/browser_catalog_smoke.py` (Playwright·Edge 필요).

`backend/domain/risk_policy.py`는 공통 계산,
`backend/services/catalog_risk.py`는 후보 조회·저장·계산 이력,
`contracts/catalog_risk/catalog.json`은 기준 데이터다.
화면 저장 시 `controls_reviewed`를 전달한다. 실제 AI 추론은 아직 연결·검증 대상이다.
