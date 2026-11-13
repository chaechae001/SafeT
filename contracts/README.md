# 데이터 형식 초안

상태: 팀 검토용 초안. 실제 API와 최종 서비스 스키마는 미구현이다.
JSON Schema는 JSON 데이터의 필드와 허용 값을 정의하는 형식이다.

- [ai-result.schema.json](ai-result.schema.json): 기존 파이프라인 실험의 최종 출력 필드 5개를 옮긴 초안.
- [examples/ai-request.json](examples/ai-request.json): 가상 분석 요청. 실제 이미지 파일은 포함하지 않는다.
- [examples/ai-response.json](examples/ai-response.json): 정보 부족 상태의 가상 응답.

기준 코드는 [기존 파이프라인 실험](../ai/experiments/261112_single_vs_pipeline_DR/261112_benchmark_DR.py)이다.
위험유형 ID는 [기존 분류 체계](../ai/experiments/261111_franchise_training_v3_DR/261111_taxonomy_DR.json)를 참조했다.
이는 실험용 잠정 분류이며 전문가가 승인한 안전 기준을 뜻하지 않는다.

## 상태 해석

| assessment_state | 의미 |
|---|---|
| candidate | 위험유형 후보가 있다. hazard_labels는 한 개 이상이다. |
| insufficient_information | 정보가 부족하다. hazard_labels는 빈 배열이다. |
| out_of_scope | 분석 범위 밖의 요청이다. hazard_labels는 빈 배열이다. |

빈 배열은 안전 판정이 아니다. 이 형식에는 위험등급이나 승인 상태가 없다.
gas_leak_status는 기존 실험과 같이 not_determinable만 허용한다.
사진만으로 가스 누출을 확정할 수 없다는 제한을 유지한다.

## 서비스 연결 전에 정할 내용

요청 ID 연결, 인증·매장 권한, 파일 참조 방식, 비동기 상태와 오류 형식을 정한다.
관찰 사실·OCR 원문·추론을 구분하고 근거 출처와 정보 부족 항목을 전달하는 형식을 정한다.
법령 근거와 권고자료를 구분한다. 사용자 검토·수정·승인 이력은 AI 출력과 분리한다.
현재 초안만으로 위 기능이 구현되었다고 판단하지 않는다.

CI는 이 JSON 파일들의 구문과 기존 실험의 자체 검사를 확인한다.
JSON Schema 전용 검증과 실제 API 연결 검사는 아직 포함하지 않는다.
