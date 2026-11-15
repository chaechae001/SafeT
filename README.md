# Safe-T For Franchise

치킨 전문점부터 시작하는 프랜차이즈 매장 안전점검 지원 프로젝트다.
사진과 작업 설명을 분석해 위험유형 후보와 근거를 제시하고, 사람의 검토를 지원하는 것을 목표로 한다.

현재 공유된 구현은 AI 실험 코드다. 웹 화면, 서비스 API, 서비스용 AI 연결은 미구현이다.
아래 서비스 역할과 데이터 형식은 개발 준비를 위한 초안이다. 팀의 확정 요구사항으로 취급하지 않는다.
위험수준, 법적 적합성, 조치 완료를 AI가 자동 확정하지 않는다.

## 저장소 구조

| 경로 | 역할과 현재 상태 |
|---|---|
| [frontend/](frontend/README.md) | 점검 입력·결과·검토 화면. 안내만 준비했다. |
| [backend/](backend/README.md) | 사용자·매장 권한, 파일, 분석 요청, 검토·개선 이력. 안내만 준비했다. |
| [ai/](ai/README.md) | 기존 실험 코드와 향후 서비스 코드를 구분한다. |
| [contracts/](contracts/README.md) | 요청·응답 예시와 AI 출력 형식 초안. |
| [docs/architecture.md](docs/architecture.md) | 구성과 데이터 흐름. |
| [docs/data-guide.md](docs/data-guide.md) | 외부 데이터·모델의 준비와 공유 원칙. |
| [.github/](.github/) | 작업 요청·PR 양식과 CPU 자체 검사. |

기존 AI 실험 폴더와 파일 이름을 유지한다. 기술 스택은 이 구조화 작업에서 선택하지 않았다.

## 시작하기

1. 담당 영역의 README를 읽는다.
2. AI 실험을 확인할 때는 아래 자체 검사를 실행한다.
3. 전체 추론·학습은 [AI 실험 안내](ai/experiments/README.md)의 데이터·Cloud 환경 조건부터 확인한다.

저장소 루트에서 Python 3.11로 실행한다. 아래 검사는 표준 라이브러리만 사용한다.

```bash
python ai/experiments/261111_franchise_training_v3_DR/261111_train_v3_DR.py --self-test
python ai/experiments/261112_model_selection_DR/261112_compare_models_DR.py --self-test
python ai/experiments/261112_single_vs_pipeline_DR/261112_benchmark_DR.py --self-test
```

자체 검사는 GPU 추론, 학습, OCR 또는 현장 안전 성능을 검증하지 않는다.
Cloud 관측 환경은 Python 3.10.14다. CI의 Python 3.11은 CPU 자체 검사 전용이다.

## 협업 방식

- `main`에서 `feat/기능명`, `fix/문제명`, `chore/작업명` 브랜치를 만든다.
- PR(Pull Request: 코드 변경 검토 요청)에 변경 내용, 검증 결과와 남은 문제를 쓴다.
- 검토 후 병합한다. 초기에는 별도 `develop` 브랜치를 두지 않는다.
- 기존 팀원 변경을 보존한다. 명시적 요청 없이 푸시·병합·리베이스하지 않는다.

`main` 보호 설정은 관리자 작업으로 남아 있다.
권장 설정은 PR 승인 1명, 기본 검사 통과, 강제 푸시·삭제 차단이다.
자동 검사를 추가하는 것만으로 병합 제한이 적용되지는 않는다.

## 자료와 결정의 기준

요구사항·회의·팀 결정은 [공식 Safe-T Notion](https://app.notion.com/p/Safe-T_-409a5d647ec5806ba57df6e84f77d545)에서 관리한다.
코드와 구현 상태는 GitHub에서 확인한다. 이 작업에서는 Notion을 새로 조회하거나 수정하지 않았다.

원본 데이터·사진·영상·모델 가중치는 권한이 확인된 외부 저장소에서 관리한다.
GitHub에는 코드, 데이터 버전·해시, 준비 방법과 공유 가능한 예시를 둔다.
API 키, 비밀번호와 실제 매장 식별정보를 커밋하지 않는다.

## 참고

구조화 기준일: 2026-11-13, Asia/Seoul.
기존 AI 안내는 [ai/experiments/README.md](ai/experiments/README.md)에 원문 그대로 보존했다.
기존 환경·선별·검증 JSON 3개는 루트 경로를 유지했다.
