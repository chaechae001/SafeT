## 목표
사진·글·음성 전사와 사업장 정보를 공통 입력으로 정리하고, 탐지 연결·입력 품질·오류 처리를 검증한다.

## Input → Output
- Input: 기존 평가표 생성 요청, 사업장 기기 목록, 기존 SAM 탐지 응답.
- Output: `input.schema.json`을 만족하는 `input.json`.
- 함수: `build_context(raw_request, detection_result=None)`.

## 구현 순서
1. 현재 `CreateAssessment`와 `make_input`의 입력·탐지 계약을 확인한다.
2. 사진 형식·용량·개수, 빈 입력, 기기 ID를 검사한다.
3. 기존 SAM 3 호출과 사진 캐시를 연결하고 사진별 기기 후보를 정리한다.
4. 탐지 클래스→표준 기기 ID를 연결한다. 미등록 클래스는 임의 ID를 만들지 않고 기록한다.
5. 글·전사의 원문·부정 표현·수치를 유지하고 TEXT/VOICE/PHOTO1 근거 ID를 붙인다.
6. 사진별·기기별 중복 탐지를 요약한다. 탐지 원본·점수·모델 버전은 서버 기록에 보존한다.
7. 검색용 equipment_ids와 모델용 media 요약을 만든다.
8. 혼합 입력·오탐·미탐·타임아웃·재시도·캐시를 검증하고 호출 지연을 기록한다.

## 품질 검사
| 입력 | 기대 결과 |
| --- | --- |
| 글만 | TEXT 원문과 부정 표현 보존 |
| 전사만 | VOICE 원문 유지. 없는 음성 내용을 보충하지 않음 |
| 사진만 | PHOTO별 탐지 후보. 물기·온도·작동 여부 단정 없음 |
| 사진+글 | 출처를 구분하고 상충 정보 보존 |
| 탐지 0건 | 기기를 만들어 넣지 않음. 글이 있으면 검색 가능 |
| 동일 사진 반복 | 동일 설정의 캐시 재사용 |
| 탐지 실패 | 원본 보존, 오류 반환. 정상 탐지 0건과 구분 |

기존 탐지 임계값을 기준선으로 유지한다. 변경이 필요하면 같은 샘플에서 누락·오탐·시간을 비교해 설정 변경 PR로 제출한다. 독립 근거 없이 임계값을 바꾸지 않는다. 원본 음성 업로드는 새로 만들지 않고 기존 전사 경로를 사용한다.

## 편집 파일
- `ai/assessment_authoring/input_adapter.py`
- `ai/assessment_authoring/detection_adapter.py`
- `ai/assessment_authoring/tests/test_input.py`
- `ai/assessment_authoring/tests/test_detection.py`
- `ai/assessment_authoring/fixtures/input/`

기존 탐지 함수를 재사용하며 동일 기능을 복제하지 않는다. `backend/services/catalog_ai.py`의 공용 호출부는 통합 담당에게 연결 패치 또는 함수 사용법을 전달한다.

## 전달 파일
- 구현 코드와 호출 방법.
- 정상·전사·사진·혼합·탐지 0건의 `input.json`.
- 탐지 실패·잘못된 입력의 오류 예시.
- 기기 매핑 목록과 미등록 목록.
- 캐시·지연·누락/오탐 검사 결과. 원본 사진은 Git에 포함하지 않는다.

## 완료 기준
Schema 통과, 근거 ID 중복 없음, 기기/시나리오 ID 혼동 없음, 원문 유실 없음, 실패와 탐지 0건 구분, 캐시 동작 확인. 실제 모델 검사와 mock 검사를 나눠 기록한다.

## 공통 계약 보강

INTERFACES.md를 따른다. 기기 ID는 reference/equipment_ids.json에 등록된 값만 사용한다.
사업장 기기 목록은 equipment_inventory로 구분하고 examples/input_variants를 참고한다.

## 시작
고정 탐지 응답으로 먼저 구현한다. 검색·LLM을 기다리지 않는다. 공통 `examples/*/input.json`을 출력 형태로 참고한다.

## 개발 AI 작업 지시
```text
기존 CreateAssessment·make_input·SAM 연결을 읽고 input_adapter와 detection_adapter를 구현해줘.
공통 input.schema.json을 만족하고 원문·부정·수치·출처를 보존해라.
기존 탐지 호출·캐시를 재사용하고 사진별 기기 요약·표준 ID를 제공해라.
기기 후보를 작동·조치 유효성·위험도로 해석하지 마라.
정상/0건/실패/중복/캐시/혼합 입력을 검사하고 검색·생성·공용 서비스 파일은 수정하지 마라.
```

