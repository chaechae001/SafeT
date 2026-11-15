# 기능별 API

FastAPI에서 요청을 받고 응답하는 코드를 둡니다.

- 예: `auth.py`, `workplaces.py`, `assessments.py`.
- 입력 검증 후 업무 처리는 `../services/`로 연결합니다.
- 인증·사업장 접근 권한은 관련 요청마다 확인합니다.
- 실제 API는 후속 작업에서 구현합니다.
