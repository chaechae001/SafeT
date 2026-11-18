# Elice 배포 연결 검토 · 2026-11-17

커밋·푸시 없음. SafeT-final-integration의 기존 미커밋 통합본 위에 적용했다.

최신 후속 결과: [사진 없는 실제 초안 검사](live-text-ai-review-20261118.md). 아래 기본 연결 성공 이후 EXAONE 상태가 HTTP 500으로 변경됐으므로 현재 연결 가능 상태로 해석하지 않는다.

## 2026-11-18 키 설정 후 연결 확인

- 사용자 입력 키는 출력하거나 문서에 기록하지 않았다.
- EXAONE /health 및 /v1/models: HTTP 200, 설정된 model ID 존재.
- 합성 문장 /tokenize: HTTP 200, 입력 34토큰.
- 합성 문장 생성: HTTP 200, 비어 있지 않은 응답, 정상 종료(stop).
- 기존 output_budget 함수를 이용한 별도 합성 JSON 생성: HTTP 200, {"status":"ok"} 파싱 및 값 검증 성공. response_format=json_object 지원 확인.
- SAM /health: HTTP 500. 상태 확인 실패만 확인했으며 원인과 실제 사진 탐지 가능 여부는 확정하지 않았다. AI 서버 담당자에게 8001 포트 서비스 상태 확인 요청 필요.
- 현장 사진·개인정보·프로젝트 전체 프롬프트/카탈로그는 전송하지 않았다. 실제 평가표 초안의 품질과 전체 흐름 검증은 아직 남았다.
- DB·SMTP 값 및 서비스 모드는 변경하지 않았다. 커밋·푸시 없음.

### 나머지 .env 값은 어디에서 확인하나요?

| 항목 | 확인할 곳 | 필요한 시점 |
|---|---|---|
| DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD | 사용할 로컬 DB 생성 설정 또는 팀 DB 담당자가 제공한 접속 정보 | 웹에서 회원·사업장·평가표를 저장할 때 |
| SMTP_HOST, SMTP_PORT, SMTP_SECURITY, SMTP_USER, SMTP_PASSWORD, SMTP_FROM | 사용할 발송 서비스의 SMTP 접속 정보 | 가입 인증 메일을 실제로 보낼 때 |
| FRONTEND_ORIGINS, SHARE_BASE_URL | 실제 실행한 화면 주소 | 브라우저 연결·다른 기기에서 공유 링크 확인 시 |
| JWT_SECRET | 이미 로컬 생성됨 | 현재 값 유지 |
| SAFET_DETECTOR_API_KEY | AI 서버 담당자에게 탐지 API 인증 필요 여부 확인 | SAM 연결 시; EXAONE 키를 임의로 복사하지 않음 |

다음 순서: SAM 서버 상태 확인 → 합성 자료로 탐지 계약 검증 → 초안 전체 연결 검증 → DB 설정 후 실제 화면 통합 검증. 기본 EXAONE 연결 확인은 완료했으므로 반복할 필요 없다.

## 연결

- EXAONE: https://gdqtaahjfkzgzzxr.tunnel.elice.io/proxy/8000/v1
- model: exaone-3.5-7.8b-instruct-awq
- SAM: https://gdqtaahjfkzgzzxr.tunnel.elice.io/proxy/8001/v1/detect
- 키는 SAFET_AI_API_KEY, SAFET_DETECTOR_API_KEY 환경변수로만 설정. .env.example에는 빈 값.
- 새 값은 .env.example에만 안내했으며 실제 환경변수를 자동 변경하지 않았다.

## 변경 내용

- SAM에 request_id, score_threshold, photos[{photo_id,image_base64}] 전송. data URL 접두어를 제거한다.
- 요청 사진 1~8장, base64 해독 후 장당 12MiB 이하 검사. 기존 화면/API 업로드 제한(6장·data URL 길이 280만)은 유지한다.
- model_output 응답과 service_meta를 읽는다. 사진 ID·요청 ID·분석 상태·점수·박스 범위를 확인한다.
- partial/failed·사진 누락·잘못된 박스는 성공이나 무탐지로 바꾸지 않는다.
- 추가 detector 메타데이터는 수용한다. 서비스 내부에는 기기 후보로 변환한다.
- 기본 탐지 임계값은 배포 기본값 0.05이며 서비스 확정값이 아니다. 사진 입력 시 후보별 기기/실제 작업 확인 질문을 추가해 사용자 확인 전 확정을 막는다. 기존 답변 화면으로 오탐을 설명·수정할 수 있다. 별도 기기 편집 화면은 추가하지 않았다.
- EXAONE에는 사진 바이트 대신 탐지 JSON과 텍스트를 전달한다.
- 프롬프트 중복 필드와 전체 JSON Schema를 줄이고 필수 출력 형식만 제시한다. 서버의 응답 검증은 유지한다.
- 출력 상한 기본값은 1024토큰이다. 같은 채팅 messages를 /tokenize로 계수한 뒤 상한과 (4096 − 입력 − 여유 64) 중 작은 값으로 생성한다. 남은 공간이 256토큰 미만이면 생성 전에 안내한다. 생성 중 길이 한도에 도달하면 부분 응답을 폐기하고 입력을 줄여 재시도하도록 안내한다.
- 계수 실패나 예산 초과 시 생성하지 않고 입력을 보존한다. 설명·질문 이력·후보를 몰래 잘라서 진행하지 않는다.
- /tokenize는 기본 주소에서 /v1을 제거한 위치로 추론하며 환경변수로 같은 호스트 내 주소를 지정할 수 있다.

## 검증

- 격리 DB 포함 전체 테스트 143개 통과, 생략 없음. 기존 AnyIO 사용 중단 예정 경고 1개.
- AI 연결 단위 테스트 25개: 배포 SAM 형식, 부분 실패, 요청·사진 ID 불일치, 박스, 사진 수·base64, 토큰 경계, 사용자 확인 질문 검사.
- Python/계약 JSON 구문과 git diff --check 통과.

## 실제 키 없이 확인한 결과

- SAM /health: HTTP 500, connect ECONNREFUSED 0.0.0.0:8001.
- SAM /v1/info: 동일 오류. AI 서버 담당자의 SAM 프로세스·포트 확인 필요.
- EXAONE /health: HTTP 200.
- EXAONE /tokenize: 키 없이 합성 hello 입력 HTTP 200, count 21.
- EXAONE 생성·실제 사진 탐지는 실행하지 않았다. 실제 인증과 JSON 응답 지원은 미검증.
- 로컬 전체 프롬프트·카탈로그를 원격 /tokenize로 보내는 검사는 자동 승인 검토가 내부 자료 외부 전송 승인 필요 사유로 차단하여 수행하지 않았다.

## 인스턴스가 목록에 없을 때

1. AI 서버 담당자이 사용하는 정확한 콘솔 URL·기관/프로젝트 이름·인스턴스 상세 링크를 받아 같은 곳인지 확인한다. ECI와 런박스는 별도 서비스다.
2. 상세 링크에도 권한 오류가 나면 운영진에게 계정의 조회·접속 권한과 다른 팀원이 생성한 인스턴스 공동 이용 가능 여부를 문의한다.
3. 콘솔 목록 권한과 SSH 접속 권한은 별개다. AI 서버 담당자에게 연결 화면의 사용자 이름·SSH 주소·포트를 요청한다.
4. 운영 정책이 허용하면 AI 서버 담당자/관리자가 AI·계산 담당자의 공개키를 등록하여 SSH 접속할 수 있다. 개인키를 공유하지 않는다. 플랫폼이 키를 관리하여 직접 등록할 수 없으면 운영진에게 접속 권한 부여를 요청한다.
5. 로컬 SafeT의 AI 호출은 공개 API 주소와 서비스 API 키만 있으면 가능하며 콘솔·SSH 접근은 필수가 아니다.

공식 안내:
- https://help.elice.io/help/docs/cloud-overview
- https://help.elice.io/help/docs/elicecloud/ondemand/ssh
- https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_keymanagement
- https://docs.vllm.ai/en/v0.15.1/api/vllm/entrypoints/serve/tokenize/protocol/
