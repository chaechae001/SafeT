# GitHub 작업 기준

계약 위치: contracts/assessment_authoring/v1/
신규 구현 위치: ai/assessment_authoring/

## 순서
1. START_HERE.md의 공통 계약 브랜치 SHA로 시작한다. reference/SOURCE.json의 base_commit은 자료 원본 기준이다.
2. 같은 commit에서 feat/assessment-input, feat/assessment-retrieval-integration, feat/assessment-extraction 브랜치를 만든다.
3. 각자 고정 fixture로 구현한다.
4. 입력→검색, 검색→추출, 추출→검증·계산 경계를 검사한다.
5. 통합 담당이 서비스 호출부를 연결하고 저장·조회·PDF를 확인한다.

## 단독 편집
- 입력 담당: input_adapter.py, detection_adapter.py, test_input.py, test_detection.py, 입력 fixture.
- 검색·통합 담당: retrieval_adapter.py, mappings/, analysis_validator.py, assessment_composer.py, 공통 계약·통합 호출부.
- 추출 담당: extraction_adapter.py, system_prompt.md, test_extraction.py, 추출 fixture.

기존 catalog_ai.py 등 공용 서비스 파일은 검색·통합 담당만 직접 수정한다.
다른 담당자는 독립 모듈·호출법·출력 예시를 전달한다.
카탈로그 피해 수준·핵심 조치와 정책 행렬은 동결한다. 계산표를 별도 복제하지 않는다.
기존 탐지·RAG·모델 호출을 재사용한다. 새 인프라·모델 교체는 필수 범위가 아니다.
공개 저장소는 역할명을 사용하고 원본 현장자료·키·가중치를 제외한다.
실모델 호출은 기존 저장소의 대기 조건을 확인한 뒤 수행한다.

