# 법령 근거 추적과 자체 모델 평가

질문을 KURE-v1으로 검색하고 실제 후보 원문을 8010에 전달한다. 후처리 결과를 최종 출력으로 저장한다. `SAFET_LEGAL_EVALUATOR_ENABLED=true`이면 같은 8010 관문에서 근거 일치를 평가한다.

## 실행 환경

- `SAFET_AI_GATEWAY_URL`, `SAFET_AI_API_KEY`, `SAFET_AI_MODEL`은 기존 모델 관문 설정이다.
- `SAFET_LEGAL_WEIGHTS`, `SAFET_LEGAL_CHROMA`는 KURE-v1과 L01 저장 폴더다.
- `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`는 추적 프로젝트 연결 설정이다.
- `SAFET_LEGAL_TRACE_DIR`을 지정하면 질의별 JSON도 저장한다.
- 생성과 평가에 같은 모델을 사용한다. 검색 점수와 생성 모델 선택을 독립적으로 비교한다.

## 기록 필드

루트 실행 `Legal RAG`에서 `inputs.question`을 읽는다. `outputs.source_documents`는 생성 모델에 실제 전달한 법령 후보이며, `outputs.raw_answer`는 생성기 원응답, `outputs.answer`는 후처리 후 최종 구조화 출력이다. `outputs.evaluation`은 자체 모델의 채점 결과다. 생성과 평가의 LLM 하위 실행에 각각 토큰 수와 처리시간이 남는다.

`legal_groundedness_v1`은 원문 뒷받침, 질문 관련성, 적용 요건·예외, 위반 단정 여부, 보류 처리의 다섯 항목을 평가한다. 모든 모델 항목이 true이고 인용 무결성 검사도 통과하면 1점이다. 불일치는 0점이며 형식 오류·호출 실패는 점수 없음으로 기록한다. 인용 무결성은 청크 ID, 법령명, 조항, 원문 문장을 대조한다.

점수와 이유를 루트 실행의 `legal_groundedness_v1` 피드백에 연결한다. 점수는 최종 후처리 출력을 대상으로 한다. 검색 Recall·Precision·F1·Hit·MRR 및 원응답 자체의 품질은 별도로 측정한다. 평가 모델과 생성 모델이 같으므로 사람의 원문 대조를 함께 사용한다.

## 과거 실험 기록

원응답 JSON에서 질문·실제 후보·답변·모델·토큰·처리시간·원본 파일 해시를 가져온다. 가져온 실행에는 `historical_import` 태그를 붙이고 표시 시간은 가져온 시각이다. 당시 전체 처리시간은 `original_elapsed_seconds`에 보존한다. 당시 저장되지 않은 단계별 시간·평가 점수는 새로 만들지 않는다. 파일 해시와 문항에서 만든 고유 ID로 중복 가져오기를 방지한다.
