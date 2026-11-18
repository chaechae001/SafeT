# 현재 AI 계약

현재 서비스는 analysis.schema.json, answers.schema.json, detection.schema.json을 사용합니다.
나머지 스키마는 이전 main의 risk_state 기반 계약 참고 자료이며 현재 API에는 적용하지 않습니다.
[통합 안내](../../docs/implementation/ai-integration.md)

배포 SAM 원격 응답은 sam-response.schema.json으로 검증한 뒤 내부 탐지 후보로 정규화합니다.
