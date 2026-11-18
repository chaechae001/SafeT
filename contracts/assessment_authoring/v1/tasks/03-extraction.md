## 목표
입력과 검색된 후보를 기존 LLM에 전달하여 위험·조치 근거를 `analysis.json`으로 반환한다.

## Input → Output
- Input: `InputBundle + RetrievalBundle + catalog_snapshot`.
- Output: `analysis.schema.json`을 만족하는 분석 객체.
- 함수: `extract_analysis(context, retrieval_bundle, catalog_snapshot)`.

## 구현 순서
1. 검색 후보 ID로 카탈로그의 시나리오 설명·전체 조치 정의를 가져온다.
2. 입력 원문·후보·조치·제공된 근거·출력 스키마로 모델 메시지를 구성한다.
3. 기존 EXAONE 연결을 사용한다. 후보 배치당 구조화 호출 1회를 기본으로 한다.
4. JSON을 파싱하고 스키마를 확인한다. 응답 중단·파싱 실패는 오류로 반환한다.
5. 근거 상태를 supported/not_effective/unknown으로 작성한다.
6. 고정 사례로 프롬프트를 검증하고 출력 예시를 전달한다.

## 출력 규칙
- questions=[].
- grade/severity/signal/checked는 생성하지 않는다.
- 등록 scenario_id/control_id와 실제 media_id만 사용한다.
- 복합 조치 일부만 확인되면 unknown.
- 문헌 권고는 현재 현장 조치의 증거가 아니다.
- 사진 탐지 결과로 장치 작동·온도·물기를 단정하지 않는다.
- 부족한 사실은 assumptions에 남긴다.
- 위험도 계산·최종 평가표 조립·DB 저장은 호출하지 않는다.

## 편집 파일
- `ai/assessment_authoring/extraction_adapter.py`
- `ai/assessment_authoring/system_prompt.md`
- `ai/assessment_authoring/tests/test_extraction.py`
- `ai/assessment_authoring/fixtures/extraction/`

## 받을 파일
`schemas/input.schema.json`, `retrieval.schema.json`, `analysis.schema.json`, `reference/catalog.json`, `examples/*/input.json`, `retrieval.json`, `analysis.json`, `prompts/generation_system.txt`.

## 전달 파일
호출 함수, 프롬프트, 정상/미확인/부정/상충의 출력 JSON, 모델 설정·토큰 사용·실행 결과.
통합 담당이 최종 참조 검증과 계산을 수행할 수 있도록 입력 근거를 보존한다.

## 완료 기준
질문 0, 등급 자유 생성 0, JSON 형식 준수, 전체 조치 충족 근거 없는 supported 없음, 부정·상충·문헌/현장 근거 구분, 응답 실패 명시.

## 공통 계약 보강

INTERFACES.md의 직접 인용·자료 유형 규칙을 따른다. 기기 탐지/보유만으로 조치를 supported 처리하지 않는다.
조립 함수는 본 함수가 반환한 AnalysisBundle을 받으며 모델을 다시 호출하지 않는다.

## 시작
공통 input.json과 retrieval.json으로 구현한다. 실모델을 호출하기 전에는 mock 응답으로 파싱·계약 검사를 실행한다.

## 개발 AI 작업 지시
```text
기존 모델 연결을 사용해 extraction_adapter와 System 프롬프트를 구현해줘.
고정 input/retrieval/catalog로 시작하고 analysis.schema.json에 맞는 객체를 반환해라.
supported/not_effective/unknown과 실제 입력 근거를 작성하고 질문·등급은 생성하지 마라.
원문 부정·상충·복합 조치 일부 충족을 구분해라.
응답 중단·잘못된 JSON을 오류로 반환하고 검색·최종 계산·저장·공용 서비스 파일은 수정하지 마라.
```

