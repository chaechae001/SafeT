# 음식점 사례 검색 시작 순서

1. 이 PR의 커밋을 기준으로 개인 브랜치를 만든다. 이 폴더의 계약을 읽고, 구현과 테스트는 별도 `ai/kras_retrieval/` 경로에 둔다.
2. 사용 가능한 실제 사례 한 건을 고른다. 자료명·판본·페이지·사례 번호, 작업·위험·예방대책을 원문과 대조한다. 평가 정답과 같은 사건·복제본은 검색 자료에서 제외한다.
3. 같은 사건의 원인·피해·대책을 한 단위로 묶는다. 다른 사건의 조치를 합치지 않는다. 점검표는 문항별 행을 별도 단위로 만든다.
4. [fixtures.json](fixtures.json)의 query로 조회한다. 기기·작업별 JSON 인덱스가 정상 0건일 때만 문헌 벡터 검색을 호출한다. 출처와 조건을 확인해 아래 형식으로 반환한다.
5. [스키마](contract.schema.json)로 응답을 검사하고 실제 사례형·점검표형 각 한 건, 적중·0건·장애 테스트 결과와 재현 명령을 인계한다. 원문 자료는 배포 권한이 있는 경우에만 공개한다.

## 사례형 예제

fixture의 kras 응답에서 items를 아래 항목으로 대체해 연결을 시험한다. 내용은 합성 예제다.

```json
{
  "process_tag": [
    "move"
  ],
  "hazard_tag": [
    "slip"
  ],
  "evidence_id": "kras:fixture-k1:case:1",
  "source_version": "fixture-k1",
  "quote": "기름이 묻은 통로에서 이동하다 미끄러졌다. 통로 바닥의 기름을 제거하도록 권고했다.",
  "kind": "case",
  "document_id": "DEMO-K",
  "document_title": "연결 시험용 합성 사례집",
  "locator": "사례 1",
  "hazard_description": "기름 묻은 통로 이동 중 미끄러짐",
  "check_item": null,
  "measure_candidates": [
    "통로 바닥의 기름을 제거한다."
  ]
}
```

법령 출력은 fixtures.json의 law를 사용한다. 점검 문구와 과거 사례로 현장 조치 시행 여부를 채우지 않는다.
