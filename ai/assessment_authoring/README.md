# 검색·근거·검증·계산 구현

판단 이유는 `explanations.py`에서 검증된 입력·문헌·핵심 조치 상태·실제 등급을 연결해 작성한다.
문헌 요약은 원문 위험 문장의 중복을 제거한 발췌형 요약이며 새 원인·대책을 생성하지 않는다.
`document_summaries`는 같은 파일의 출처를 묶고 원문 연결 행·쪽을 보존한다. 원본 `document_evidence`는 변경하지 않는다.
설명 전체는 JSON 스냅샷에 저장하고, 기존 500자 DB 열에는 호환용 앞부분을 저장한다. API와 화면은 JSON의 전체 설명을 사용한다.
기존 확정본의 판단 이유는 자동 재작성하지 않는다. 변경된 판단 이유는 새 평가표에서 확인한다.

공통 기준: 4521794dfa097a73519f8c327ada44bdcdaa4787 / 계약 PR #31.
이 모듈은 input_based 경로를 독립 실행한다. 기존 배포 7514acd의 질문·사용자 조치 확인·저장 API는 유지한다.

## 실행

저장소 루트, Python 3.11 이상. 추가 패키지·GPU·배포·API 키 없이 실행한다.

```bash
python -m unittest discover -s ai/assessment_authoring/tests -v
python contracts/assessment_authoring/v1/validate.py
python -X utf8 -m ai.assessment_authoring.demo --case unknown
python -X utf8 -m ai.assessment_authoring.demo --case critical_supported
python -X utf8 -m ai.assessment_authoring.demo --case all_supported
```

demo의 입력·추출은 공통 합성 예제다. 검색·검증·계산·행 조립은 실제 구현을 실행한다.
unknown 사례는 FRY / S2 / C3 / 상, critical_supported는 C2 / 중, all_supported는 C1 / 중이다.
예상 위험도·사용자 확인 상태를 만들어 현재 등급을 덮어쓰지 않는다.

## 함수와 연결

실제 클라우드 합성 텍스트 검수는 아래 명령으로 실행한다. 기존 비공개 환경설정을 읽으며 키를 출력하지 않는다.

```bash
python -X utf8 -m ai.assessment_authoring.live_text_check --env-file "<기존 backend/.env 경로>" --output "<로컬 결과 JSON 경로>"
```

검수 도구의 입력·근거 프롬프트는 현재 조치 정의와 개선대책을 분리한다. 실제 모델 응답은 동일 계약 검증을 거친다.
표시용 rationale은 서버 문구로 조립하고 모델의 자유 설명은 원본 AnalysisBundle에 보존한다.

| 파일 | 입력 → 출력 |
| --- | --- |
| retrieval_adapter.py | InputBundle + 카탈로그 → RetrievalBundle |
| analysis_validator.py | 입력·검색·분석·카탈로그 → 검증 및 unknown 정규화된 분석 복사본 |
| assessment_composer.py | 입력·검색·분석·카탈로그 → AssessmentCore, render_assessment는 표시용 행도 반환 |
| pipeline.py | build_context·extract_analysis 함수 주입 → 입력/검색/분석/결과/검색 이력 |
| mappings/catalog_links.json | 표준 기기 ID·보수적 키워드 → 카탈로그 시나리오 ID |

입력 담당은 build_context를, 추출 담당은 extract_analysis를 구현한 뒤 run_pipeline에 넘긴다.
3개씩 후보를 나누고 전체 배치를 처리한다. 후보 0건에는 모델을 호출하지 않는다.
결과 전체를 DB 응답으로 바로 보내지 않는다. 기존 서비스의 revision·소유권·모드별 저장 게이트 연결은 후속 통합 대상이다.

## 기존 RAG 연결

백엔드 환경에서는 기존 services.rag_retrieval.candidates를 rag_provider 인자로 전달한다.
실제 데이터는 SAFET_RAG_DIR에 설정된 기존 비공개 인덱스·MANIFEST를 사용하며 해당 함수의 무결성 검사를 재사용한다.

```python
bundle, trace = retrieve_with_evidence(
    context, catalog,
    rag_provider=rag_retrieval.candidates,
    rag_links=verified_equipment_hazard_links,
)
```

rag_links는 {"기기ID:실제위험코드": ["시나리오ID"]} 형태의 검수된 연결표다.
위험코드를 시나리오 ID로 추정하거나 임의 출처를 카탈로그 문서 쪽으로 바꾸지 않는다.
실제 위험코드와 출처 응답은 trace.rag_response에 보존하고, 미연결 항목은 unmatched에 남긴다.
live_rag_check는 실제 응답을 확인한 튀김기 burn→FRY, slip→ENV 연결만 사용한다. gas·respiratory는 미매칭으로 남긴다.
합성 응답 주입 테스트는 API 연결 형태와 이력 보존을 확인한다.

기본 검색의 source_refs는 기존 카탈로그의 등록 문헌 위치다. matched는 참조 연결을 뜻하며 원문 실시간 조회나 현장 사실 검증을 뜻하지 않는다.
RAG 공급자가 설정되지 않으면 카탈로그 검색만 실행하고 trace.retrieval_mode=catalog로 기록한다.
명시적으로 공급자를 전달했는데 실패하면 예외를 전달한다. 장애를 정상 0건으로 처리하지 않는다.
검색 원문 이력에는 비공개 자료가 포함될 수 있으므로 공개 로그·PR·클라이언트에 그대로 노출하지 않는다.

## 범위와 남은 검수

- 기기 매핑은 보수적인 시작 집합이다. 미등록 관계는 unmatched로 남긴다. 일반 냉장고를 냉동실 내부 작업으로 연결하지 않는다.
- 키워드·간단한 부재 표현으로 후보를 찾는다. 문맥 전체·복합 부정·조치 전체 조건의 의미 검증은 추출 품질 검사 대상이다.
- 법령 registry는 기본 빈 목록이다. 검수된 시행일·적용조건을 거친 registry만 서버에서 주입한다.
- 현재 조치의 직접 인용은 문자열·자료 유형·ID를 검사한다. 진술의 진실성까지 검증하는 기능은 아니다.
- 성공 행은 상/중/하, 일부 미매칭은 partial, 결과 없음은 no_supported_result다.
- MATRIX는 backend/domain/risk_policy.py를 import한다. 원본 정책과 수동 evaluate는 변경하지 않는다.
- 공통 검사의 스냅샷 해시는 LF 기준이다. Windows CRLF 체크아웃에서도 동일한 원문을 검사하도록 보정했다.

## 검사 결과

독립 unittest 36개 통과: 공통 예제 5종, 등급표 9조합, ID·근거·질문·중복 거절,
누락 조치, 법령 등록, 배치 보존, 기기 오매핑 반례, RAG 실패/미매핑/이력,
추천과 현재 등급 분리, 고정 함수 연결, 모델 호출 생략.
공통 계약 33개와 저장소 지정 CPU self-test 3개도 실행한다.
합성 텍스트 한 건의 실제 EXAONE 검수를 수행했다. 동일 입력 생성 3회 중 앞선 두 응답은 검증에서 차단했고 프롬프트 보완 후 통과했다.
별도 튀김기 검수에서는 SSH로 읽은 비공개 RAG 검색 결과를 실제 모델 입력과 로컬 평가표까지 연결했다.
DB 저장·배포 화면·PDF 출력·QR·사진 검사는 포함하지 않는다. 기존 검수 배포와 병행 가능하다.

## RAG 문헌 전달

run_pipeline의 선택적 extract_with_evidence(context, batch, catalog, evidence) 콜백을 사용하면
시나리오별 실제 검색 문헌을 모델 입력에 전달할 수 있다. 기존 extract_analysis 3인자 계약은 유지한다.
live_text_check.build_messages의 document_evidence 인자는 문헌을 reference_documents로 구분한다.
최종 표시 행의 document_evidence에는 동일한 내용과 출처가 보존된다.
원본 집계 응답의 출처는 위험코드 묶음 단위다. source_evidence가 있으면 원본 연결 행의 문장·파일·쪽 정보를 함께 보존한다.
현장 조치 근거와 혼용하지 않는다. 미확인 조치의 개선 후보에도 실제 미실시를 단정하는 표현을 사용하지 않는다.
enabled=false 응답은 오류로 처리한다. 배포 웹앱의 RAG 설정은 이번 검수에서 변경하지 않았다.

### 실제 튀김기 검수 재실행

```bash
python -X utf8 -m ai.assessment_authoring.live_rag_check --env-file "<기존 backend/.env 경로>" --rag-file "<SSH로 읽은 실제 검색 응답.json>" --links-file "<manifest 해시를 확인한 연결 행.json>" --output "<저장소 밖 로컬 결과.json>"
```

links-file은 `{ "rows": [...] }` 형식이다. 검색 응답과 연결 행 파일은 같은 manifest의 retrieval 자료에서 확보한다.
evidence_qualification은 A등급의 기기 직접 언급 문장만 전달한다. 섹션명만으로 묶인 다른 기기 문장과 1:1 대응이 없는 대책 집계는 제외한다.
현재 검수 도구는 배치당 1개 시나리오로 기존 관문의 4,096 토큰 한도를 검사한다. 프롬프트·응답·문헌이 포함된 결과 파일은 비공개로 보관한다.
이 검수는 문헌 전달·계약·계산 연결을 확인하며, 원문 PDF 육안 검증이나 전체 기기 정확도 평가를 대신하지 않는다.

