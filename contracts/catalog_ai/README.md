# DB 연결 추출 계약

서버 근거 계약 버전은 `CATALOG-AI-1.1`이다. 위험도 계산 정책 버전과 별도로 관리한다. 모델 응답은 [analysis.schema.json](analysis.schema.json)을 따른다. 기준은 `backend/schemas/risk_analysis.py`다.
시나리오·조치 ID는 [DB 카탈로그](../catalog_risk/catalog.json)에 있어야 한다. 모델은 모든 연결 시나리오의 모든 조치를 present/absent/unknown으로 반환한다.
등급·피해 수준·조치 문구·자료 출처는 모델 수정 대상이 아니다. 텍스트·전사문 근거는 입력의 정확한 발췌이며 사진은 실제 콘텐츠를 전송한다.
기기 등록은 작업 수행·조치 이행 증거가 아니다. 각 근거의 `time_scope`는 `current/planned/unknown`이다. 현재 조치의 존재·부재는 current 근거로만 확정하며 계획·시점 불명 근거를 현재 조치 완료로 취급하지 않는다.

JSON 검증 후 서버가 ID 중복·참조 무결성·근거·기존 시나리오 보존을 검사한다. 미연결 관찰·적용 불명·조치 미확인·상충 정보는 질문으로 남기고 확정을 막는다.
답변은 기존 `/evals/{eval_no}/risk-answers`에 revision·question_id·answer를 보낸다. 추가 관찰은 additional_text다. 모든 요청에 로그인·소유권·작성 중 상태·revision 검사를 적용한다.
현재 위험도와 계획 이행 가정의 예상 위험도는 [main 공통 함수](../../backend/domain/risk_policy.py)의 CATALOG-MVP-1.0을 사용한다.

답변 미디어는 실제 답변만 content에 넣고 question·question_id는 별도 문맥으로 저장한다. 서버 질문은 근거 발췌 대상이 아니다.
한 요청에 최대 1000개 답변을 받으며 한 미디어로 묶는다. 기존 미확인 ID·중복 ID 검사는 유지하고 반복 입력은 300개 미디어 한도 내에서 처리한다.
이전 근거 계약의 작성 중 문서는 시점 재확인 전까지 판단 필요로 표시하고 확정을 막는다. 이미 확정된 문서의 저장 결과는 이전 분석 기록으로 조회한다.
