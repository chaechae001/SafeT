# Safe-T

소규모 사업장의 위험성평가 작성을 돕는 서비스입니다.
현장 사진과 작업 설명을 바탕으로 AI 초안을 만들고 사용자가 확인합니다.

## 기술

- 화면: HTML·CSS·JavaScript
- 서버: Python 3.11·FastAPI
- DB: MariaDB·ChromaDB
- AI: EXAONE 3.5 7.8B Instruct AWQ

## 구조

| 폴더 | 역할 |
|---|---|
| [frontend/](frontend/README.md) | 화면·스타일·사용자 입력 |
| [backend/](backend/README.md) | API·업무 처리·DB |
| [ai/](ai/README.md) | 모델 추론·RAG·기존 실험 |
| [analysis/](analysis/README.md) | 데이터 분석·평가 |
| [contracts/](contracts/README.md) | 공통 JSON·예시 |
| docs/ | 설계·결정 기록 |
| .github/ | Issue·PR 양식·자동 검사 |

## 개발

현재는 기본 폴더와 AI 실험 코드가 준비돼 있습니다. 화면·API·서비스용 AI 연결은 개발 예정입니다.

작업별 브랜치에서 개발하고 PR 검토 후 main에 병합합니다.
비밀정보·현장 원본·모델 가중치는 커밋하지 않습니다.

## 확정된 위험도 개발 기준

[2026-11-17 최종 합의](docs/implementation/risk-development-agreement.md)를 우선 적용한다.
현재 위험도와 개선대책 저장 후 예상 위험도를 제공한다. 화면설계서 37–41쪽 부록은 이번 범위에서 제외한다.

## AI 통합 검토

[AI 연결·설정·검토 안내](docs/implementation/ai-integration.md).
GitHub 기록의 SAM 기기 후보 → EXAONE 텍스트 추천 구조를 공통 위험도 계산에 연결한다.
실제 배포 주소·모델 ID 확인 및 실추론 검증은 대기 중이다.
