# 개발 시작용 최소 폴더 구조

이번 변경은 합의한 단순 구조의 위치 안내입니다. 화면·API·DB·AI 실행 기능을 구현한 상태는 아닙니다.

| 경로 | 역할 |
|---|---|
| [frontend/pages/](../frontend/pages/README.md) | 화면별 HTML |
| [frontend/css/](../frontend/css/README.md) | 공통·화면별 스타일 |
| [frontend/js/](../frontend/js/README.md) | 화면 동작·API 호출 |
| [frontend/public/](../frontend/public/README.md) | 공용 이미지 |
| [backend/](../backend/README.md) | FastAPI·MariaDB 업무 처리 |
| [ai/src/](../ai/src/README.md) | 서비스용 모델 추론·RAG |
| [ai/prompts/](../ai/prompts/README.md) | 프롬프트 |
| [ai/experiments/](../ai/experiments/README.md) | 기존 실험 보존 |
| [analysis/](../analysis/README.md) | 신규 분석·평가 |
| [contracts/](../contracts/README.md) | 공통 JSON과 예시 |
| docs/ | 설계 링크·결정 기록 |
| .github/ | Issue·PR 양식·자동 검사 |

## 기능 연결

프런트엔드 → 백엔드 → 서비스용 AI.
MariaDB는 사용자·평가표 등 업무 기록, ChromaDB는 RAG 문서·임베딩 검색을 담당합니다.
모델은 현재 Qwen 2.5-VL-3B를 사용하되 교체할 수 있도록 구현합니다.
Python 3.11은 목표 환경이며, 기존 Cloud 관측값과 GPU 호환성 검증을 구분합니다.
Python 버전은 3.11로 고정합니다(`.python-version`). 예외: SAM 3는 Python 3.12 이상이 필요해 별도 venv/컨테이너로 실행하고, 본체(3.11)와는 탐지 결과 JSON으로만 연결한다.

## 충돌을 줄이는 규칙

- 담당자를 폴더에 고정하지 않습니다. Issue마다 목적·수정 파일·담당자·검토자·완료 조건을 정합니다.
- 공통 CSS·JSON·DB 정의·설치 설정 변경은 먼저 공유합니다.
- 문서 전체 버전을 고정하지 않고, Issue에 참고 화면·확인 날짜·합의한 동작을 기록합니다. 요구사항 V1.8은 이번 구조의 기준으로 사용하지 않습니다.
- 새 화면설계가 나와도 진행 중 작업의 범위를 자동 변경하지 않고 관련 Issue에서 영향을 합의합니다.
- 최신 main에서 작업별 브랜치를 만들고 PR로 검토합니다. 본인이 작성한 PR의 승인은 다른 팀원에게 요청합니다.
- 폴더는 README로 표시하고 실제 파일은 필요할 때 추가합니다.
- 기존 실험·루트 JSON·contracts 초안은 보존합니다.

## 다음 작업

1. 이 구조 PR을 검토·병합합니다.
2. 최신 main에서 HTML 화면 뼈대용 브랜치를 만듭니다.
3. 전체 화면 이동·공통 UI·합성 데이터 표시·실행 방법을 담은 PR을 만듭니다.
4. 화면·API·AI의 공통 JSON을 맞춘 뒤 기능별로 나눠 개발합니다.

실제 현장 사진·업로드·모델 가중치·DB 데이터·Chroma 인덱스·비밀정보는 Git에 올리지 않습니다.
