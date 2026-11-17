# 음식점 위험성평가 v2 — 서비스 연결 기준

작성: 2026-11-17. 팀 기준 페이지: <https://app.notion.com/p/41aa5d647ec5805384b2ff43f58dd35d>

## 구현 상태

기존 PR #10 `feat/assessment-authoring-flow`의 `6278ef38b042fc44d00ab3aaee16b63ae3718799`를 기준으로 `feat/restaurant-risk-v2` 브랜치에서 구현했다. PR #10 브랜치를 대상으로 별도 Draft PR에서 검토하며, main 병합·운영 배포는 별도 단계다. 기존 화면·인증·MariaDB를 유지하며 특정 Cloud 공급사나 모델을 확정하지 않았다.

사용자는 Cloud 호출용 API 키 발급을 완료했다고 알렸고, 모델명과 연결 주소는 추후 확인 예정이다. 따라서 코드·API 계약·UI·DB 흐름을 연결하고 합성 모델 응답으로 통합 검증했으며, 실제 Cloud 사진 추론 정확도·음성 인식 정확도·GPU 추론은 검증하지 않았다.

## 흐름

1. 기존 평가표 작성 화면에서 사진(실제 이미지), 글, 음성 전사문을 입력한다. 음성은 기존 브라우저 SpeechRecognition을 사용하며 미지원 시 전사문 직접 입력을 제공한다. 서버 STT·원본 오디오 업로드는 이번 연결 범위에 없다.
2. 서버가 등록 기기 스냅샷을 포함해 미디어별 ID를 부여한다. 사진은 Cloud의 이미지 콘텐츠로 전달하며 파일명만 보고 분석했다고 하지 않는다. 전사 부정어·수치는 미확인 정보로 유지한다.
3. 버전 고정 프롬프트·27개 범주 카탈로그·출력 스키마를 모델에 전달한다. 입력 자료 속 지시는 데이터로 취급한다.
4. 모델은 위험 경로·피해 후보·조치 후보·근거·미확인 질문을 반환한다. JSON Schema와 ID·출처·법령·핵심 조치의 일관성을 서버가 검증한다.
5. 별도 결정 코드가 상/중/하 및 잠정 범위를 계산한다. 오류·정보 부족을 하로 대체하지 않는다.
6. 초안 화면의 추가 질문에 답하거나 변경 관찰을 입력하면 같은 평가표를 재분석한다. 질문 ID·소유권·revision을 검사하고 기존 위험 ID·입력·선택·담당자는 보존한다.
7. 현재 조치를 바꾸면 이전 신호를 N으로 만들고 재판정을 요구한다. 대책 계획 선택은 조치 완료 증거가 아니다.
8. 후보·잠정·미확인 질문·재판정 대기가 남으면 확정을 차단한다. 확정 후 원인·피해·판정 근거·조치 상태·자료 출처를 읽기 전용으로 조회한다.

## 등급 정책

공식 안내서의 예시를 서비스에 구현한 보수적 운영안이다. 공인 사고 확률식·유일한 공식 산식이 아니다.

| 피해 | C1 필요한 조치 유효 | C2 핵심 유효·일부 미흡 | C3 핵심 결여·무효 |
|---|---|---|---|
| S1 경미·업무 지장 없음 | 하 | 중 | 중 |
| S2 치료·회복 필요 | 중 | 중 | 상 |
| S3 사망·영구장해 가능 | 상 | 상 | 상 |

- 현실적으로 가능한 현재 사고 경로를 기준으로 한다. 기기 보유만으로 S3 확정 금지.
- S3 경로가 남아 있으면 C1이어도 상. 검증된 제거·격리로 경로가 사라지면 `closed`로 보존하고 남은 경로를 별도 평가한다.
- 급박한 위험·검증된 현행 법정기준 미충족은 상. 동일원인 미해소 아차사고는 최소 중.
- 미확인은 미설치와 다르다. 후보는 등급 null, 확인된 위험의 미확정 S/C는 가능한 범위와 잠정 최댓값으로 표시한다. 잠정값은 기존 R/Y/G 확정 신호에 넣지 않고 N과 별도 배지로 보여준다.
- 작업장 집계는 평가 범위의 최고 등급·잠정 최고 등급·미확인 수이다. 평균·안전 확률·사업장 안전 인증·자동 작업허가는 제공하지 않는다.
- 현재 서비스의 신뢰된 법령 레지스트리는 비어 있다. 현행 조문 검증 서비스가 연결되기 전 모델이 법 위반을 확정할 수 없다.

## 코드와 공통 계약

| 경로 | 역할 |
|---|---|
| [프롬프트](../../ai/restaurant_risk/system_prompt.md) | 사진·텍스트·음성 전사 분석 및 질문·근거 생성 규칙 |
| [카탈로그](../../ai/restaurant_risk/knowledge_catalog.json) | 27개 범주·핵심/보완 조치·질문·자료 출처·과거 수치 |
| [페이지 반영대장](../../ai/restaurant_risk/page_coverage.json) | 추가 실무길잡이 지정 66쪽의 처리 이력 |
| [입력 스키마](../../contracts/restaurant_risk_v2/input.schema.json) | 미디어 ID·사진 위치·음성 전사·법령 신뢰 경계 |
| [AI 분석 스키마](../../contracts/restaurant_risk_v2/analysis.schema.json) | 사고 경로·S/C 후보·증거·추가 질문 |
| [최종 출력 스키마](../../contracts/restaurant_risk_v2/output.schema.json) | 판정·범위·요약·확인 상태 |
| [예시](../../contracts/restaurant_risk_v2/examples.json) | 실제 현장과 구분된 가상 사례 8개 |
| [Cloud 연결](../../backend/services/restaurant_risk.py) | 정규화·실제 이미지 전달·검증·화면용 매핑 |
| [판정 코드](../../backend/services/restaurant_risk_engine.py) | 고정 정책·상향 규칙·미확인 처리 |
| [질문·근거 화면](../../frontend/js/risk-assessment.js) | 잠정/확정 구분·질문·증거·출처 |

`eval_mst.risk_state`에 현재 정책 버전·입력 근거·판정 JSON·추가 질문·위험 ID와 평가 항목 ID의 연결을 저장한다. 사진 원본은 기존 `eval_file`에만 저장하고 재분석 시 복원한다. 답변은 입력 미디어로 누적하고 이전 판정 요약은 history에 보존한다. 기존 사용자의 조치·대책·담당자·예정일은 재분석으로 삭제하지 않는다. 이전 추천의 적합성도 담당자가 다시 검토한다.

새 API: `POST /evals/{eval_no}/risk-answers`

```json
{
  "revision": 2,
  "answers": [{"question_id": "Q1", "answer": "현재 물기가 남아 있고 출입 통제가 없습니다."}],
  "additional_text": "같은 통로로 뜨거운 국을 운반합니다."
}
```

응답은 기존 평가 상세에 `risk_assessment`, `risk_needs_reassessment`, 각 item의 `risk`를 추가한다. 판정 필드·정책·법령 레지스트리는 클라이언트 수정 대상이 아니다. 오류 시 기존 보고서와 revision을 보존한다.

## Cloud 연결 설정

기존 `backend/.env`에 아래 값을 설정한다. 키를 프런트엔드·노션·커밋에 넣지 않는다. 모델명은 임의로 추정하지 않는다.

```dotenv
SAFET_ASSESSMENT_MODE=restaurant_v2
SAFET_AI_BASE_URL=https://YOUR-CLOUD-ENDPOINT/v1
SAFET_AI_MODEL=YOUR-CONFIRMED-MULTIMODAL-MODEL
SAFET_AI_API_KEY=YOUR-PRIVATE-KEY
SAFET_AI_MAX_TOKENS=12000
```

API 어댑터는 `/chat/completions`에 `messages`, `image_url`, `response_format: json_object`를 보내는 호환 형식이다. Cloud가 이 형식을 지원하는지 확인해야 한다. 다른 계약이면 어댑터만 교체하고 입력·판정 계약은 유지한다. 모델에는 카탈로그와 JSON 스키마를 포함하므로 충분한 컨텍스트와 JSON 출력 능력이 필요하다. 응답을 스키마에 억지로 맞추거나 오류 후 임의 등급을 생성하지 않는다.

```bash
python -m pip install -r backend/requirements.txt
# 개인 개발 DB 설정을 확인하고 백업한 뒤 실행
python backend/run_local.py --migrate
```

추가 SQL은 [20261117_restaurant_risk_v2.sql](../../backend/migrations/20261117_restaurant_risk_v2.sql)이며 `risk_state LONGTEXT`를 추가한다. 기존 평가표 값은 변경하지 않는다. `--demo`는 시험 고정값 모드이므로 실제 Cloud 연결 시험에서는 사용하지 않는다. 설정이 없으면 기본 unavailable 모드이며, restaurant_v2를 켰는데 주소/모델이 없거나 검증에 실패하면 명시적 오류를 반환한다.

## 검증

- 별도 MariaDB 11.8.3 테스트 컨테이너에서 기존 테스트와 신규 정책/API 테스트: 98개 통과, skip 0개.
- 이번 검증 Python은 3.12이며 저장소의 기존 목표 버전은 3.11이다. 배포 환경의 의존성·모델 호환성 확인은 별도로 필요하다.
- 실제 HTTP 요청 형식 검사: 텍스트·음성 전사·기기 및 사진 `image_url` 전송. 응답은 합성 fixture.
- Edge 모바일 화면: 추가 질문 → 답변 재판정 → 현재 조치 변경 → 재판정 → 대책·담당자 → 확정 → 읽기 전용 근거 조회. JavaScript 오류 없음.
- 변경 JavaScript 문법·contracts JSON·기존 AI CPU 자체 검사 3개 통과.
- 실제 Cloud 추론·음성 ASR 정확도·GPU·OCR·현장 판정 일치율은 미검증.

```bash
python -m pytest backend/unit_tests backend/tests -q
# 실제 UI 검사는 격리된 *_test DB와 Playwright + Edge 필요
python backend/unit_tests/browser_risk_smoke.py
```

## 이후 작업에서 지켜야 할 기준

이 노션 페이지와 `RESTAURANT-3LEVEL-2.0` 정책·프롬프트·스키마를 함께 참조한다. 피해/조치 매핑 또는 확정 조건을 바꾸면 정책 버전·스키마·테스트·노션 변경 기록을 함께 갱신한다. ‘정보 부족→하’, ‘체크 개수 평균’, ‘장갑을 모든 회전체에 일괄 권고’, ‘대책 계획을 완료로 처리’, ‘구형 자료를 현행 법 위반 근거로 사용’하는 변경을 금지한다.

근거: A 인쇄 9–15쪽(PDF13–19), B 인쇄50–64쪽(PDF58–72), C 인쇄94–96·103–165쪽(PDF95–97·104–166). 과거 제품별 응급처치는 최신 SDS·전문지침 검증 전 생성하지 않는다. 공식 게시물: <https://www.moel.go.kr/policy/policydata/view.do?bbs_seq=20230301846>
