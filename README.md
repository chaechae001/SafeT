# Safe-T

소규모 사업장의 위험성평가 작성을 돕는 서비스입니다.
현장 사진과 작업 설명을 바탕으로 AI 초안을 만들고 사용자가 확인합니다.

## 기술

- 화면: HTML·CSS·JavaScript
- 서버: Python 3.11·FastAPI
- Python: 3.11 고정(`.python-version`). 예외: SAM 3는 Python 3.12 이상이 필요해 별도 venv/컨테이너로 실행하고, 본체(3.11)와는 탐지 결과 JSON으로만 연결한다.
- DB: MariaDB·ChromaDB
- AI: EXAONE 3.5 7.8B Instruct AWQ (변경 가능)

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

평가표 작성·저장·확정 화면/API와 음식점 위험성평가 v2 연결이 구현돼 있습니다. 사진·텍스트·음성 전사 입력, 추가 질문, 고정 기준의 상/중/하 판정과 근거를 연결합니다. 실제 Cloud 모델의 주소·모델명 설정 및 추론 검증은 남아 있습니다.

실행·API·검증·정책 변경 기준은 [음식점 위험성평가 v2](docs/risk/restaurant-risk-v2.md)를 참고하세요. 팀 공유 기준은 [위험성평가 기준 셋업](https://app.notion.com/p/41aa5d647ec5805384b2ff43f58dd35d)입니다.

작업별 브랜치에서 개발하고 PR 검토 후 main에 병합합니다.
비밀정보·현장 원본·모델 가중치는 커밋하지 않습니다.
