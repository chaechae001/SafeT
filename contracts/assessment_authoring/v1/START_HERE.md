# 같은 기준에서 시작하기

## 1. 공통 브랜치 받기

저장소 루트에서 실행한다. 기존 작업은 먼저 별도 커밋하거나 보관한다.

```bash
git fetch origin docs/assessment-authoring-v3-contracts
git rev-parse origin/docs/assessment-authoring-v3-contracts
```

세 명이 출력 SHA를 공유하고 같은 SHA를 사용한다. 아래 BASE_SHA는 그 실제 40자리 SHA로 바꾼다.
reference/SOURCE.json의 base_commit은 자료 원본 커밋이므로 작업 시작점으로 사용하지 않는다.

| 담당 | 본인이 실행할 명령 하나 |
| --- | --- |
| 입력 | git switch -c feat/assessment-input BASE_SHA |
| 검색·통합 | git switch -c feat/assessment-retrieval-integration BASE_SHA |
| 추출 | git switch -c feat/assessment-extraction BASE_SHA |

계약 PR 병합 전에도 이 SHA에서 개발할 수 있다. 병합 후에는 통합 담당이 공통 기준 갱신을 한 번 공지한다.
변경된 main을 각자 임의로 섞어 시작하지 않는다.

## 2. 읽고 검사하기

README.md → INTERFACES.md → 담당 tasks 문서 → schemas → examples 순서로 읽는다.

```bash
python contracts/assessment_authoring/v1/validate.py
```

기대 결과는 PASS: 33 checks다. Python 3.11 이상, 추가 패키지·GPU·API 키가 필요 없다.

## 3. 동시에 구현하기

| 담당 | 먼저 만들 것 | 다른 담당 결과를 대신할 파일 | 제출 |
| --- | --- | --- | --- |
| 입력 | build_context·탐지 adapter | 기존 탐지 mock + examples/input_variants | input.json, 입력/탐지 검사, 매핑 |
| 검색·통합 | retrieve_evidence와 compose_assessment | examples의 input/retrieval/analysis | retrieval.json, 핵심 결과, 검사 |
| 추출 | extract_analysis·프롬프트 | examples의 input/retrieval + catalog | analysis.json, 프롬프트, 검사 |

구현 위치와 단독 편집 파일은 tasks/01-input.md, 02-retrieval-integration.md, 03-extraction.md를 따른다.
공통 Schema·골든 예제·서비스 연결은 검색·통합 담당이 수정한다. 계약 변경은 세 담당의 소비 예제를 함께 갱신한 별도 PR로 처리한다.

## 4. 연결하기

1. 각 담당 PR에 함수 호출법·출력 JSON·검사 결과를 붙인다.
2. 입력 → 검색 경계를 실제 input.json으로 확인한다.
3. 검색 → 추출 → compose_assessment 경계를 실제 retrieval/analysis로 확인한다.
4. 세 기능 PR을 통합 브랜치에 모으고 공통 검사를 다시 실행한다.
5. 검색·통합 담당이 API·저장·조회 연결을 진행하고 화면·PDF를 이어 붙인다.
6. 이후 화면 작업은 파일별로 나누어 진행한다. 공통 서비스 파일을 동시에 편집하지 않는다.

완료 기준: 정상·unknown·partial·no_supported_result 일치, 잘못된 근거 차단,
현재/예상 분리, 사용자 추가 확인 없이 저장 가능, 과거 결과 조회 유지.
실모델 검사는 기존 저장소의 호출 대기 조건이 해제된 뒤 실행하고 mock 검사와 구분하여 기록한다.

