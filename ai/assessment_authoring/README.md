# 검색·근거·검증·계산 구현

공통 기준: 5a882f6148d614d341cbdbe9643967da2f915457 / 계약 PR #31.
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
실제 위험코드와 출처 응답은 trace.rag_response에 보존하고, 미연결 매핑은 trace.diagnostics에 남긴다.
현재 저장소에 비공개 인덱스가 없으므로 실제 코드별 연결표를 만들어냈다고 주장하지 않는다.
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

독립 unittest 21개 통과: 공통 예제 5종, 등급표 9조합, ID·근거·질문·중복 거절,
누락 조치, 법령 등록, 배치 보존, 기기 오매핑 반례, RAG 실패/미매핑/이력,
추천과 현재 등급 분리, 고정 함수 연결, 모델 호출 생략.
공통 계약 33개와 저장소 지정 CPU self-test 3개도 실행한다.
실제 클라우드·DB·PDF·QR·실모델 검사는 포함하지 않는다. 기존 검수 배포와 병행 가능하다.


## 검토와 표시

출력은 담당자가 실제 작업과 근거를 검토할 초안이다. 기기에서 찾았지만 작업이 미확인인 후보와 입력에서 작업을 부정한 후보는 공통 결과인 core.review_candidates에 각각 work_unconfirmed와 input_denies_work로 담는다. 담당자가 실제 작업 확인 또는 비적용 결정을 내리기 전까지 검토 대상으로 남는다. 검색 진단은 retrieval_trace에 기록하며 실제 미매칭 위험만 평가표에 표시한다.
source_refs는 등록된 카탈로그 순서의 처음 두 건이다. 검색 관련도 순위를 뜻하지 않는다.
계약·원문 근거 검사는 #31과 같은 함수를 사용한다. 서비스 저장·확정 연결 시 권한, revision, 검토 이력, 명시적 확정을 서버에서 확인한다.
