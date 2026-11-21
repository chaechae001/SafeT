> 최신 배포 연결 규격·설정·검증 상태는 [Elice 연결 검토](elice-connection.md)를 우선 참조하세요. 아래 배포 전 기록과 제안 SAM 규격은 이전 단계입니다.

# AI 연결 통합 — 검토용

2026-11-17. 상태: 로컬 구현·모의 모델 통합 검증 완료 / 실제 모델 서버는 배포 전으로 진행.
사용자 확인: 팀원의 배포 정보 답변을 아직 받지 못했으므로 배포 전 상태로 관리한다.
사용자 요청에 따라 커밋·푸시·원격 PR 수정·병합은 검토 승인 후 수행한다.

## 이번 변경

AI 후보 → 공통 DB 시나리오 → 사용자 확인 → 현재·예상 위험도 계산을 연결한다.
등급은 `backend/domain/risk_policy.py`만 계산한다. 신규 평가표는 FOOD-3LEVEL-1.2, 기존 평가표는 저장 당시 CATALOG-MVP-1.1([위험도 합의](risk-development-agreement.md)).
현재 main의 AI 연결을 최종 합의 계약으로 통합한다. 등급 계산은 공통 정책에 둔다.

| 구간 | 구현 |
|---|---|
| 텍스트·전사문 | 서버에서 추천 모델로 전달 |
| 사진 | 별도 SAM 호환 탐지 서비스에 사진 전달 → 기기 후보 JSON → 텍스트 모델 |
| AI 결과 | 등록된 시나리오 ID·입력 근거·추가 질문만 허용. 모델이 등급을 반환하면 거절 |
| 조치·대책 | 선택한 시나리오의 DB 기준 목록 사용. 자동 체크하지 않음 |
| 추가 질문 | 답변 재분석. 기존 항목·조치 선택·계획·담당자·예정일 보존 |
| 재분석 후 | 현재 조치 목록 확인을 해제해 사용자 재확인 요구 |
| 저장 | 현재·예상 결과는 동일한 공통 계산 함수 사용. 질문이 남으면 N |
| 오류 | 임의 등급·고정 결과로 대체하지 않음. 재분석 오류 시 이전 문서·revision 보존 |
| 근거 | 모델·정책·프롬프트 버전, 입력 근거, 질문·답변 이력 저장·조회 |

기준 밖 위험이 발견되거나 기존 위험 후보가 재분석에서 사라지면 분석을 적용하지 않는다.
후보당 시스템 사진 확인 질문을 포함해 최대 11개, 전체 100개 질문/누적 답변 한도를 둔다. 한도를 넘으면 오류로 안내하며 질문을 잘라내지 않는다.
현재 구조는 전체 카탈로그의 후보 설명을 모델에 제공한다. 벡터 검색·별도 ChromaDB RAG는 연결하지 않았다.
실제 모델의 컨텍스트 길이·JSON 출력 지원 여부와 현장 정확도는 아직 검증하지 않았다.

## GitHub에서 확인한 모델 구성

확인 당시 main: `2d3fa24ea60da556505ec339f2b59e99da6c6a4b`.
[AI 작업 문서](https://github.com/chaechae001/SafeT/blob/main/ai/README.md)에 다음 구성이 기재돼 있다.

- 사진: SAM 3, Python 3.12 별도 프로세스/컨테이너
- 음성: faster-whisper + large-v3-turbo
- 텍스트: EXAONE 3.5 7.8B Instruct AWQ, Python 3.11
- GPU 모델 순차 적재는 추론 서버가 담당해야 한다.

[서비스 AI 코드 안내](https://github.com/chaechae001/SafeT/blob/main/ai/src/README.md)는 미구현 상태다.
이전 실험의 text_model.json은 Qwen 모델을 가리키지만, 배포된 서비스 모델 ID로 사용하지 않는다.
실제 API 주소·인증 상태·SAM 요청 계약·배포 model ID는 공개된 설정에서 확인되지 않았다.
키가 저장소에 없다는 사실로 서버에 키가 없다고 판단하지 않는다.

원본 음성 업로드·서버 STT는 기존 화면/API에 없어서 이번에는 브라우저 전사문을 입력으로 유지한다.
사진 탐지 서비스 구현·GPU 모델 적재/해제는 별도 인프라 연결 작업이며 이번 서버 어댑터가 대신 실행하지 않는다.

## 필요한 실제 연결 정보

| 설정 | 필요한 값 |
|---|---|
| SAFET_AI_BASE_URL | 텍스트 모델의 API 기본 주소. 현재 어댑터는 뒤에 /chat/completions를 붙임 |
| SAFET_AI_MODEL | 서버가 실제로 받는 model ID. 모델 표시 이름과 다를 수 있음 |
| SAFET_AI_API_KEY | 필요한 경우 서버 환경변수에만 저장 |
| SAFET_DETECTOR_URL | SAM 결과를 제공하는 HTTP 요청의 전체 주소 |
| SAFET_DETECTOR_API_KEY | 필요한 경우 서버 환경변수에만 저장 |

EXAONE에는 사진 바이트를 보내지 않는다. 사진이 있는데 탐지 서버 설정이 없으면 명시적 오류를 반환한다.
탐지 JSON에는 기기 후보만 포함하며 보호장치 작동·가스누출·안전 여부를 확인했다고 해석하지 않는다.

## 제안된 SAM 연결 계약

이는 배포 서버에서 확인된 규격이 아니라 이번 어댑터의 검토 가능한 연결 규격이다.
실제 서버 규격이 다르면 탐지 어댑터만 조정한다.

요청:
```json
{"photos":[{"id":"PHOTO1","data":"data:image/png;base64,...","place":"주방"}]}
```
응답:
```json
{"model":"배포된 탐지 모델 ID","detections":[{"photo_id":"PHOTO1","equipment":"튀김기","confidence":0.8}]}
```

분석 응답 예시:
```json
{"candidates":[{"scenario_id":"FRY","rationale":"사용자가 튀김 작업을 보고함","evidence":[{"media_id":"TEXT","statement":"튀김 조리 중"}],"questions":[{"id":"Q1","text":"현재 실제로 튀김 작업을 하나요?"}]}],"unmatched_risks":[]}
```

## 실행과 검사

환경변수 예시는 `backend/.env.example`에 있다. 실서버 설정을 넣은 뒤 개인/격리 DB에서:
```powershell
python backend/run_local.py --ai --migrate
```
`--check`는 로컬 설정·DB만 확인한다. 서버 연결 성공이나 모델 정확도 검증을 의미하지 않는다.
텍스트 모델 호출은 chat/completions 형식과 JSON 출력 요청을 가정한다. 실제 서버의 지원 여부는 연결 정보 확보 후 검증한다.

```powershell
python -m pytest backend/unit_tests/test_catalog_ai.py -q
# 별도 *_test DB와 기존 ERD/마이그레이션 준비 후
python -m pytest backend/unit_tests backend/tests -q
python backend/unit_tests/browser_catalog_smoke.py --ai-fixture
```
마지막 명령은 명시적으로 모의 AI·SAM 응답을 사용한다. 실제 모델을 호출하지 않는다.

## 주요 변경 파일

- `backend/services/catalog_ai.py`: 탐지 서비스·텍스트 모델 호출과 후보 검증
- `backend/schemas/catalog_ai.py`, `contracts/catalog_ai/`: 분석·탐지·답변 계약
- `backend/services/catalog_risk.py`: AI 후보를 기존 기준 데이터·공통 계산에 연결
- `backend/services/assessment.py`, `backend/routers/assessment.py`: 생성·키워드 추가·답변 재분석
- `frontend/js/catalog-ai.js`: 근거·추가 질문·답변 화면
- `backend/run_local.py`, `backend/.env.example`: AI 모드 실행·설정

DB는 기존 catalog_state를 사용하므로 이번 AI 통합만을 위한 새 DB 열은 추가하지 않는다.
PDF 37–41쪽 부록 기능은 이번 범위에서 제외한다.

## GitHub 반영 전 검토

1. 후보 생성·질문·계산 흐름과 SAM 연결 계약 검토
2. 앞선 위험도 최종 합의 변경과 이번 AI 변경을 함께 반영할 범위 확인
3. 승인 후 최신 main과 변경 충돌 확인 → 로컬 커밋 → 요청한 원격 반영

현재 통합 기반은 PR #19가 병합된 main b91d1e35721b492b4e3afd2fb2606f1908889529이다.
PR #19의 문서·서명·공유·전체 탭·저장 확인창과 개발 서버 변경을 유지했다.

## 이전 로컬 검증 기록 (통합 전)

- Python 3.11, 격리 safet_agreed_policy_test DB: 전체 109개 통과, skip 0.
- HTTP 모의 전송: 사진은 탐지 서비스로만 전달, 텍스트 모델에는 탐지 JSON만 전달함을 확인.
- 응답 검증: 임의 등급·없는 시나리오·없는 근거·중복 질문·응답 잘림·대용량·401·잘못된 JSON을 거절.
- API: 미답변 질문의 임의 삭제 차단, 재분석 실패 롤백, revision·확정 잠금·인증 검사, 생성 모드 유지.
- Edge 모바일: 질문 → 답변 → 현재 조치 확인 → 현재 상/예상 중 → 확정 → 근거 재조회 통과, JavaScript 오류 없음.
- CPU 자체 검사 3개, Python/JavaScript 구문, JSON·문서 링크, git diff --check 통과.
- 모의 모델·모의 SAM 응답을 사용했다. EXAONE/SAM/faster-whisper 실제 추론 정확도·성능·GPU 전환·비용은 검증하지 않았다.
- 테스트 도구의 기존 AnyIO 사용 중단 예정 경고 1개가 있으며 테스트 실패는 아니다.


## 배포 전 진행 기준 (사용자 추가 확인)

- 서버 주소·배포 모델 ID는 팀원 답변 전까지 빈 설정으로 유지한다.
- 일반 개발은 `python backend/run_local.py --catalog --migrate`로 DB 기준 계산·저장·화면을 확인한다.
- AI 연결 흐름 검사는 격리 테스트 DB에서 `python backend/unit_tests/browser_catalog_smoke.py --ai-fixture`로 수행한다. 모의 응답은 이 테스트 실행에만 적용한다.
- 실제 서버 정보가 없는 상태에서 `--ai`를 실행하면 설정 오류를 안내하며 모의 응답으로 자동 전환하지 않는다.
- 팀원 답변 후 순서: API 주소·배포 모델 ID·인증 방식 확인 → SAM 요청 형식 조정 → 텍스트 1건 → 사진 포함 1건 → 대표 현장 사례의 누락·추천·판정 검증.
- GPU 서버 배포와 원본 음성 STT 연결은 이번 로컬 어댑터 구현 완료에 포함되지 않는다.
- 커밋·GitHub 반영은 사용자 검토 승인 대기 상태를 유지한다.
