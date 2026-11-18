# AI 연결 안내

현재 구현과 실행 방법은 [AI 통합 문서](ai-integration.md)를 참조합니다.
최종 위험도 기준은 [개발 합의](risk-development-agreement.md)를 따릅니다.

이전 main의 risk_state 기반 추출 계약은 신규 생성·재분석에서 사용하지 않습니다.
기존 정책 1.0 평가표는 조회할 수 있지만 수정·확정 시 POLICY_CHANGED로 차단하며 새 기준으로 작성해야 합니다.
기존 사진·입력·근거 데이터는 DB에 보존합니다. 자동 데이터 변환은 수행하지 않습니다.
