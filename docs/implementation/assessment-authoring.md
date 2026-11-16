# 평가표 작성 → 저장 → 확정 구현

화면설계서에 따른 평가표 작성·저장·확정 기능과 실행 방법입니다.

## 구현 범위

| 단계 | 구현 |
|---|---|
| 기본정보 | 로그인 사용자의 활성 사업장 조회, 한국 기준 오늘/계정 이름 제안, 참여자 추가·삭제 |
| 현장입력 | 글, 사진(최대 6장, PNG/JPEG/WebP 장당 2MB), 음성 전사문 보존 |
| 보유기기 | 선택한 사업장의 등록 기기를 조회하고 평가 시점 스냅샷 저장 |
| 초안 | 생성 요청 중복 키로 재시도 중복 방지. DB 응답 후에만 이동. 오류 시 입력 유지 |
| 위험 상세 | 현재 조치/없음, 대책 선택·직접 추가, 초록 유지/대책 추가 명시 선택 |
| 일괄 지정 | 작성자·참여자 선택 또는 직접 담당자 입력, 예정일. 기본 지정 없음 |
| 저장 | 필수 누락 허용, DB 저장·재조회, 수정 충돌(revision) 검사 |
| 확정 | 서버·화면 필수값 검사 → 확인 창 → 트랜잭션 잠금 → 해당 평가표 읽기 전용(S08)으로 이동 |
| 확정 조회 | 실제 저장된 평가표·상세 읽기 전용, 서버에서도 이후 편집 거부 |

현재 신호 N, 현재 조치 미확인, 초록 처리 미선택, 필요 대책·담당·예정일 누락은 확정할 수 없습니다. 예상 신호 N 자체는 현재 신호 N과 구별하며, 실제 조치 결과로 표시하지 않습니다. 입력 형식·길이·소유권 검사는 저장에도 적용합니다.

## 모델 연결 상태와 데모

현재 저장소의 실제 AI 초안/위험도/기기 인식 서비스는 미연결입니다. `backend/services/assessment_provider.py`가 연결 지점입니다. 기본 실행은 `unavailable`: 입력과 N 초안을 저장하지만 확정하지 않습니다. 모델이 판단한 척 고정 등급이나 법령을 표시하지 않습니다.

흐름만 시험하려면 **로컬 개발 서버에서만** `SAFET_ASSESSMENT_MODE=demo`를 지정하고 API를 다시 시작합니다. demo는 실제 입력을 분석하지 않고 고정 합성 3건을 반환하며 문서에 출처가 영구 저장됩니다. 저장 시 예상 신호도 효과를 추론하지 않고 현재 신호를 유지하는 시험값입니다. 기존 실제 문서를 데모로 바꾸지 않습니다. 화면에 시험용 표시가 항상 보입니다.

- PowerShell: `$env:SAFET_ASSESSMENT_MODE="demo"`
- bash: `export SAFET_ASSESSMENT_MODE=demo`
- 해제 후 새로 생성한 문서는 다시 N입니다. 합성 문서는 테스트 후 별도로 정리하세요.

음성은 브라우저 SpeechRecognition이 지원될 때만 전사합니다. 미지원/권한 거절 시 글·전사문 직접 입력을 제공합니다. 원본 녹음 파일 저장과 서버 STT, 사진 기기 인식, 실제 AI 재판단은 후속 연결입니다. 사진은 일단 `eval_file.file_text`에 검증한 data URL로 저장하므로 별도 파일 볼륨 없이 복원됩니다. 운영 전 외부 파일 저장소로 이전할 수 있도록 경계를 분리해야 합니다.

## DB 적용 및 실행

기존 ERD V1.1 테이블이 있는 개발 DB에서 백업 후 [추가 필드 SQL](../../backend/migrations/20261116_assessment_authoring.sql)을 한 번 실행합니다. 기존 테이블 생성 SQL 전체를 재실행하지 않습니다.

추가 필드는 eval_mst의 `request_key`(중복 요청 방지), `revision`(동시 수정 감지), `generation_source`(demo/unavailable 출처) 3개입니다. 기존 평가 상세·조치·기기·참여자 테이블을 그대로 사용합니다.

```bash
# backend/.env의 기존 DB/JWT 설정을 사용
python -m pip install -r backend/requirements.txt
# backend 폴더에서
python -m uvicorn main:app --reload --port 8001
# 별도 터미널, 저장소 루트에서
python -m http.server 8000 --directory frontend
```

`http://localhost:8000/pages/login.html`에서 로그인 → 새 평가표 작성. 기존 화면 코드와 같은 포트를 사용합니다. PR #8의 인증·탭별 평가표 선택 기능이 포함된 최신 main을 기준으로 합니다.

## API

| 메서드·경로 | 설명 |
|---|---|
| POST /evals | 기본정보·현장입력·request_key(UUID)로 초안 생성 및 저장 |
| GET /evals/{id} | 소유자 문서·입력·기기·참여자·위험·조치 조회 |
| PUT /evals/{id} | revision 및 전체 항목 편집 저장. 판정 신호·AI 추천 문구 수정 금지 |
| POST /evals/{id}/confirm | 같은 편집 본문 검사 후 확정. 실패 시 전부 롤백 |
| POST /evals/{id}/items | revision·keyword로 추가 항목 생성. 이미 확정한 문서는 차단 |

400: 항목·조치 소속 불일치 / 401: 로그인 필요 / 404: 소유자 아님·삭제된 문서 / 409: 확정 잠금·동시 수정 / 422: 형식 또는 필수 누락. 필수 누락은 `detail.errors[{index,field,message}]`를 반환해 해당 필드로 이동합니다. 클라이언트가 보낸 판정 신호·출처는 거부합니다.

## 기존 기능과의 연결

인증·사업장·목록 기능은 유지하고, 평가표 작성 API와 화면을 연결합니다. `write.js`, `api.js`, `home.js` 대신 `assessment-write.js`를 추가 로드합니다.

## 검사

테스트 전용 ERD V1.1 DB에 추가 SQL을 적용하고 환경변수를 테스트 DB로 지정합니다. 기존 테스트는 DB가 없으면 skip하므로 **실제 pass 수와 skip 여부를 확인**하세요. 테스트 DB에만 실행하세요.

```bash
python -m pytest backend/tests -q
node --check frontend/js/draft.js
node --check frontend/js/assessment-write.js
node --check frontend/js/assessment-result.js
```

[신규 DB 통합 테스트](../../backend/tests/test_assessment.py)는 생성·미완성 저장·재조회·확정·잠금, 소유권, stale revision, 트랜잭션 롤백, 중복 생성, N 확정 차단, 등급 변조 차단, 사진 입력을 검증합니다.


## 화면 동작

- 확정 직후 해당 평가표의 읽기 전용 화면으로 이동합니다.
- 확정본 하단에는 내 평가표로·엑셀 다운로드만 표시합니다. 서명·공유는 목록 카드에서 진입합니다.
- 위험 상세는 선택한 조치와 대책만 표시하며 수정할 수 없습니다.
- 기본정보의 날짜·작성자는 제안값을 채우고, 대책 담당자·예정일은 빈칸으로 둡니다.
- 이전·다음 이동은 입력을 유지하고, 평가표 저장 버튼을 눌러야 DB에 저장합니다.

## 검증 결과

- 별도 MariaDB 테스트 DB: 75개 통과, 생략 없음.
- 모바일 작성 → 미완성 저장 → 확정 → 읽기 전용 조회 및 재조회 통과.
- 읽기 전용 상세 이동·서명 칸 지우기·모바일/데스크톱 표시 확인, JavaScript 오류 없음.
- CPU 자체 검사 3개, JSON·문서 링크·JavaScript 문법 검사 통과.

실제 AI 판단, 원본 음성 저장·서버 STT, 사진 기기 인식, 서명 DB 저장, 엑셀·공유·휴지통·후속업무는 미연결입니다.
