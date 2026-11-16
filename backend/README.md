# 백엔드

목표 환경은 Python 3.11·FastAPI·MariaDB입니다. 현재는 폴더와 안내만 있으며 실행할 API 서버·DB 연결 코드는 없습니다.

| 경로 | 역할 |
|---|---|
| [routers/](routers/README.md) | 기능별 API 입구 |
| [services/](services/README.md) | 업무 처리·규칙 |
| [models/](models/README.md) | DB 테이블 정의 |
| [schemas/](schemas/README.md) | 요청·응답 형식 |

구현 시 `main.py`에 앱 시작, `database.py`에 DB 연결을 추가합니다.
실행 코드·패키지·환경변수·DB 초기화·변경 이력·검사 방법은 해당 구현 PR에 기록합니다.

기본정보·현장입력·기기·초안 생성·저장·확정은 기능별 파일로 나눌 수 있습니다.
공통 평가표 ID·상태·JSON을 먼저 합의하고 같은 테이블·공통 형식 변경은 조율합니다.

- 관련 요청마다 사용자·사업장 접근 권한을 확인합니다.
- 업로드 형식·크기 제한은 구현 전에 정합니다.
- AI 실행 실패·대기·정보 부족을 구분합니다.
- AI 원본 결과와 사용자 확인값은 구분해서 저장합니다.
- API 키·DB 비밀번호는 프런트엔드에 전달하지 않습니다.

연결 전 [데이터 형식 초안](../contracts/README.md)을 검토합니다. 세부 담당자는 Issue에서 정합니다.

## MariaDB 연결 (2026-11-16 추가)

로컬 Docker의 MariaDB에 연결하는 코드만 추가했습니다. 화면(프런트엔드)과 API 연결은 아직 하지 않았습니다.

| 파일 | 역할 |
|---|---|
| `database.py` | `.env`에서 접속 정보를 읽어 SQLAlchemy 엔진·세션을 만듭니다. |
| `main.py` | FastAPI 앱 시작점. `GET /health/db`로 연결 상태를 확인합니다. |
| `check_db.py` | 터미널에서 연결과 테이블 정의서 V1.1의 테이블 19개를 확인합니다(데이터는 읽지 않음). |
| `.env.example` | 환경변수 예시. 복사해서 `.env`를 만듭니다. |
| `requirements.txt` | 패키지 목록과 용도 주석 |

### 처음 설정 (저장소 루트, Windows)

```bash
# 1. 가상환경과 패키지
python -m venv backend\.venv
backend\.venv\Scripts\python -m pip install -r backend\requirements.txt

# 2. 환경변수: 복사한 뒤 backend\.env 의 DB_PASSWORD 를 채웁니다
copy backend\.env.example backend\.env

# 3. 연결 확인
backend\.venv\Scripts\python backend\check_db.py
```

### API 서버 실행

```bash
cd backend
.venv\Scripts\python -m uvicorn main:app --reload --port 8001
# 확인: http://localhost:8001/health/db  ·  API 문서: http://localhost:8001/docs
```

프런트엔드 확인 서버가 8000번을 쓰므로 API는 8001번으로 띄웁니다.

### 주의

- `.env`와 `.venv/`는 `.gitignore`에 있어 GitHub에 올라가지 않습니다. 비밀번호는 `.env`에만 적습니다.
- 접속 오류가 나도 응답과 로그에 비밀번호·접속 주소를 출력하지 않습니다.
- 이 PC에 Python 3.11이 없어 3.12로 확인했습니다. 목표 환경(3.11)에서는 아직 실행하지 않았습니다.
- `requirements.txt`는 한글 주석 때문에 BOM이 있는 UTF-8로 저장했습니다. BOM이 없으면 Windows pip가 cp949로 읽다가 실패합니다.

## 회원가입 API (2026-11-16 추가)

화면설계서 07쪽 A02(이메일 → 인증 코드 → 비밀번호 → 이름)의 백엔드 API입니다. 화면과의 연결은 아직 하지 않았습니다.

| 메서드·경로 | 하는 일 | 주요 오류 |
|---|---|---|
| `POST /auth/signup/code` `{email}` | 인증 코드 6자리를 만들어 메일로 보냅니다. | 409 이미 가입, 429 60초 안 재요청, 503 메일 설정 없음, 502 발송 실패 |
| `POST /auth/signup/code/verify` `{email, code}` | 가장 최근 코드와 비교합니다. | 400 요청 없음·만료·불일치(n/5), 429 5번 틀림 |
| `POST /auth/signup` `{email, password, name}` | 인증을 마친 이메일만 가입합니다. | 400 미인증·인증 후 30분 경과, 409 이미 가입 |

### 규칙 (2026-11-16 결정)

- 인증 코드: 숫자 6자리, 5분 뒤 만료, 5번 틀리면 다시 요청, 재요청은 60초 뒤부터
- 비밀번호: 8자 이상, bcrypt 해시로 `user.pw`에 저장. 인증 코드는 SHA-256 해시로만 저장합니다.
- 인증을 마친 뒤 30분 안에 가입을 마쳐야 합니다.
- 이미 가입한 이메일은 인증 요청 단계에서 안내합니다(설계서 07쪽).
- 오류 응답은 임시 형식 `{"detail": {"code": "...", "message": "..."}}`입니다. 공통 오류 형식은 [contracts](../contracts/README.md)에서 합의 후 맞춥니다.
- ORM 모델은 합의 전이라(`models/README.md`) 테이블은 SQL로 직접 다룹니다.

| 위치 | 파일 |
|---|---|
| `routers/` | `auth.py`(회원가입 API), `health.py`(DB 상태 확인) |
| `schemas/` | `auth.py`(요청·응답 형식과 입력 검사) |
| `services/` | `auth.py`(회원가입 규칙), `mailer.py`(SMTP 메일 발송) |
| `tests/` | `test_auth.py`(회원가입 테스트 16개), `conftest.py` |

### 메일 발송 설정

`backend/.env`의 `SMTP_*` 값을 채웁니다(설명은 `.env.example`). Gmail은 계정 비밀번호가 아니라 앱 비밀번호를 씁니다.
값이 비어 있으면 인증 요청이 503(`MAIL_NOT_CONFIGURED`)을 돌려주고 DB에 아무것도 저장하지 않습니다.

### 테스트

```bash
cd backend
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest -q
```

- 로컬 MariaDB(`.env`)를 씁니다. 연결이 안 되면 테스트를 건너뜁니다.
- 메일은 실제로 보내지 않고 가짜 발송 함수로 확인합니다.
- `@test.invalid` 테스트 이메일로 만든 행은 테스트가 끝나면 지웁니다.
- 실제 SMTP 발송은 메일 계정 설정 후 직접 확인해야 합니다(아직 미확인).

## 화면 연결 · CORS (2026-11-16 추가)

- 회원가입 화면(`frontend/pages/login.html#v-signup`)이 위 회원가입 API를 부릅니다(`frontend/js/api.js`, `login.js`).
- 화면(8000번)과 API(8001번)는 포트가 달라, `main.py`에서 화면 주소만 허용합니다(CORS).
  - 허용 주소는 `.env`의 `FRONTEND_ORIGINS`(쉼표 구분)이고, 비우면 `http://localhost:8000,http://127.0.0.1:8000`입니다.
- 함께 띄우기 (터미널 2개, 저장소 루트 기준)

```bash
# 1) API 서버
cd backend
.venv\Scripts\python -m uvicorn main:app --reload --port 8001

# 2) 화면 서버
python -m http.server 8000 --directory frontend
# → http://localhost:8000/pages/login.html#v-signup
```

- 테스트에 CORS 허용·차단 확인 2개를 추가해 회원가입 테스트는 모두 18개입니다.

## 로그인 API · JWT (2026-11-16 추가)

| 메서드·경로 | 하는 일 | 주요 오류 |
|---|---|---|
| `POST /auth/login` `{email, password}` | 비밀번호(bcrypt)를 확인하고 토큰(JWT)과 `has_workplace`(사용 중인 사업장 유무)를 돌려줍니다. | 401 `LOGIN_FAILED`, 503 `AUTH_NOT_CONFIGURED` |
| `GET /auth/me` (헤더 `Authorization: Bearer <토큰>`) | 현재 로그인한 사용자와 `has_workplace`를 돌려줍니다. | 401 `LOGIN_REQUIRED`, `TOKEN_EXPIRED` |

- 로그인 방식은 토큰(JWT, HS256)으로 결정했습니다(2026-11-16).
  - 로그인이 필요한 API는 `routers/auth.py`의 `current_user` 의존성으로 사용자를 확인합니다.
- 로그인에 실패하면 "이메일 또는 비밀번호가 맞지 않아요" 한 가지로만 안내합니다. 가입되지 않은 이메일도 비밀번호 비교 시간을 같게 맞춥니다.
- 사업장 유무는 `workplaces.use_yn`이 `'Y'`(또는 비어 있음)인 행이 있는지로 판단합니다. 삭제한 사업장(`'N'`)은 세지 않습니다.
- `.env` 설정
  - `JWT_SECRET`: 서명용 비밀키. 32자 이상이어야 하며, 없으면 로그인이 503으로 실패합니다. 사람·PC마다 다르게 만들고 공유하거나 커밋하지 않습니다.
    만드는 방법: `backend\.venv\Scripts\python -c "import secrets; print(secrets.token_hex(32))"`
  - `JWT_EXPIRE_MINUTES`: 토큰 유효 시간(분). 기본 480분(8시간)입니다.
- 화면은 토큰을 `sessionStorage`에 보관합니다. 탭을 닫으면 로그아웃되므로 로그인 유지 기능은 없습니다(설계서 07쪽).
- 테스트: `tests/test_login.py` 11개 추가, 전체 29개입니다. 사업장이 있는 경우는 테스트용 업종·사업장을 만들었다가 지웁니다.
- 아직 없는 것: 다른 화면의 로그인 확인(로그인 안 하면 로그인 화면으로 보내기), 토큰 만료 후 원래 화면 복구(설계서 07쪽), 로그인 실패 횟수 제한(설계서에 규칙 없음).
  - 이 중 로그인 확인과 만료 후 복구는 화면 쪽에서 만들었습니다(`frontend/js/README.md`). 실패 횟수 제한은 아직 없습니다.

## 사업장 API (2026-11-16 추가)

화면설계서 08~09쪽 B01(목록)·B02(등록)·B02-E(수정)·삭제입니다. 모두 로그인이 필요합니다.

| 메서드·경로 | 하는 일 |
|---|---|
| `GET /biz-categories` | 업종 목록 (`biz_category`) |
| `GET /biz-categories/{biz_code}/machines` | 업종별 기기 (`machine_category`, `use_yn='Y'`만) |
| `GET /workplaces` | 내 사업장(`use_yn='Y'`만), 보유 기기, 작성 중 평가표 수(`draft_count`) |
| `GET /workplaces/{work_no}` | 사업장 한 곳 (수정 화면용) |
| `POST /workplaces` `{workplace, biz_code, machine_codes[], custom_machines[]}` | 등록 (201, `work_no`) |
| `PUT /workplaces/{work_no}` `{workplace, machine_codes[], custom_machines[]}` | 수정. 업종은 바꿀 수 없습니다. |
| `DELETE /workplaces/{work_no}` | 삭제 = `use_yn='N'`(204). 사업장·기기·평가표 행은 지우지 않습니다. |

- 남의 사업장이나 삭제한 사업장은 조회·수정·삭제할 수 없습니다. 둘 다 404(`WORKPLACE_NOT_FOUND`)로 답합니다.
- 기기
  - 선택한 업종에 없는 기기, 사용 안 함 기기는 400(`INVALID_MACHINE`)입니다.
  - 직접 추가 기기는 `workplace_machine.machine_code = NULL`로 저장합니다.
  - 앞뒤 공백을 정리하고 같은 이름은 합칩니다. 업종 목록에 있는 이름이면 그 기기로 저장합니다.
- 수정하면 보유 기기를 통째로 바꿉니다. 이미 작성한 평가표의 기기 기록(`eval_machine`)에는 영향이 없습니다.
- 기준 데이터(`biz_category`, `machine_category`)는 API로 만들지 않습니다. DB에 직접 넣습니다(현재 로컬: 치킨 `CHK` 1개, 기기 18개).
- 테스트: `tests/test_workplaces.py` 12개 추가, 전체 41개입니다. 테스트용 업종·기기를 따로 만들고 끝나면 지우므로 실제 기준 데이터는 건드리지 않습니다.

## 내 평가표 목록 API (2026-11-16 추가)

`GET /evals?tab=C&start=YYYY-MM-DD&end=YYYY-MM-DD&work_no=&page=1` · 로그인 필요 · 화면설계서 10쪽 H01

- 탭 (같은 평가표가 여러 탭에 나올 수 있음. 05쪽, 36쪽 2번 "임시 처리"를 따름)

  | tab | 조건 |
  |---|---|
  | `W` 작성 중 | `eval_status = 'W'` |
  | `C` 확정 (기본) | `eval_status IN ('C','S','A')` (확정된 평가표 전체) |
  | `S` 서명 완료 | `sign_end_dt`가 있음 |
  | `A` 조치 완료 | `eval_status = 'A'` |

- 기간: 평가일(`eval_dt`) 기준이며 시작일·종료일을 모두 포함합니다. 시작일이 종료일보다 늦으면 400(`INVALID_PERIOD`)입니다.
- 사업장: 내 평가표만 봅니다. 삭제한 사업장의 평가표도 계속 보입니다(08쪽).
- 휴지통(`del_yn='Y'`)은 뺍니다. 10개씩, 평가일 최근 순입니다.
- 응답: `{items[], total, page, size}`
  - 각 평가표에는 사업장명, 평가일, 작성자, 상태, 서명이 필요한 참여 근로자 수(`member_count`)와 서명한 수(`signed_count`)가 들어 있습니다.
  - `signed_count`는 `eval_sign`에서 `signer_type='WO'`이고 `sign_yn='Y'`인 사람 수입니다.
- 빈 값(`work_no=` 등)을 보내면 422가 나옵니다. 화면은 빈 값을 보내지 않습니다.
- 테스트: `tests/test_evaluations.py` 7개 추가, 전체 48개입니다. 테스트 정리 순서를 평가표 → 사업장 → 업종으로 고쳤습니다.
- 확인 필요: 참여 근로자가 0명인 확정 평가표는 '서명하기'만 표시합니다(서명 필요 인원 규칙이 설계서에 없음).
