# DB 연결 추출 계약

모델 응답은 [analysis.schema.json](analysis.schema.json)을 따른다. 기준은 `backend/schemas/risk_analysis.py`다.
시나리오·조치 ID는 [DB 카탈로그](../catalog_risk/catalog.json)에 있어야 한다. 모델은 모든 연결 시나리오의 모든 조치를 present/absent/unknown으로 반환한다.
등급·피해 수준·조치 문구·자료 출처는 모델 수정 대상이 아니다. 텍스트·전사문 근거는 입력의 정확한 발췌이며 사진은 실제 콘텐츠를 전송한다.
기기 등록은 작업 수행·조치 이행 증거가 아니다. 계획을 현재 조치 완료로 취급하지 않는다.

JSON 검증 후 서버가 ID 중복·참조 무결성·근거·기존 시나리오 보존을 검사한다. 미연결 관찰·적용 불명·조치 미확인·상충 정보는 질문으로 남기고 확정을 막는다.
답변은 기존 `/evals/{eval_no}/risk-answers`에 revision·question_id·answer를 보낸다. 추가 관찰은 additional_text다. 모든 요청에 로그인·소유권·작성 중 상태·revision 검사를 적용한다.
현재 위험도와 계획 이행 가정의 예상 위험도는 [main 공통 함수](../../backend/domain/risk_policy.py)의 CATALOG-MVP-1.0을 사용한다.
