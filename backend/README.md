> 최신 EXAONE/SAM 연결 규격과 4096토큰 제한: [Elice 연결 검토](../docs/implementation/elice-connection.md).

# 백엔드

입력 기반 평가의 사진 입력과 검색 근거를 화면·DB까지 연결하는 실행 방법과 계약은
[검색 근거의 화면·DB 연결](../docs/implementation/authoring-rag-local-integration.md)을 참고한다.

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

## 비밀번호 재설정 API (2026-11-16 추가)

화면설계서 07쪽에는 '비밀번호 재설정' 링크만 있어서, 규칙은 2026-11-16에 이렇게 정했습니다.

| 메서드·경로 | 하는 일 |
|---|---|
| `POST /auth/password/code` `{email}` | 가입한 이메일이면 6자리 코드를 메일로 보냅니다. 가입하지 않은 이메일도 같은 응답을 주고, 메일·기록은 남기지 않습니다. |
| `POST /auth/password/code/verify` `{email, code}` | 코드를 확인합니다. 가입 안 함과 요청 안 함은 구분하지 않고 `CODE_MISMATCH`로 답합니다. |
| `POST /auth/password/reset` `{email, password}` | 인증 후 30분 안에 새 비밀번호를 저장합니다(bcrypt, 8자 이상). |

- 코드 규칙(6자리·5분·5회·60초)과 메일 발송은 회원가입과 같습니다. 메일 제목은 "[Safe-T] 비밀번호 재설정 인증 코드"입니다(`mailer.send_code(purpose="reset")`).
- 회원가입과 같은 `email_verifications` 테이블을 쓰며, 용도 칸이 없어서 아래처럼 구분합니다.
  - 계정을 만든 뒤(또는 마지막으로 비밀번호를 바꾼 뒤, `COALESCE(upt_dt, ins_dt)`)에 보낸 코드만 재설정에 인정합니다.
  - 그래서 회원가입 때 인증한 기록이나 이미 쓴 재설정 코드로는 비밀번호를 바꿀 수 없습니다.
- 재설정하면 기존 로그인을 모두 끝냅니다.
  - 토큰에 비밀번호 버전(`pwv` = `user.upt_dt` 초)을 넣고, 버전이 다르면 401(`LOGIN_REQUIRED`, "비밀번호가 바뀌어 다시 로그인해 주세요.")로 답합니다.
  - 이 변경 전에 발급한 토큰은 한 번 다시 로그인해야 합니다.
  - 주의: 나중에 이름 수정 등으로 `user.upt_dt`를 바꾸면 그때도 로그아웃됩니다. 그런 기능을 만들면 비밀번호 변경 시각 칸을 따로 두는 것이 좋습니다.
- 테스트: `tests/test_password_reset.py` 9개 추가, 전체 57개입니다.

## 보완: 일회용 인증 토큰 (2026-11-16)

검토에서 나온 문제를 고쳤습니다.
- 이전에는 가입·재설정이 '그 이메일에 인증 완료 기록이 있는지'만 봤습니다. 그래서 주인이 코드를 확인한 뒤 30분 안에 이메일만 아는 다른 사람이 가입하거나, 비밀번호를 바꿔 계정을 가로챌 수 있었습니다.
- 이미 인증된 이메일은 틀린 코드로 확인해도 성공으로 답했습니다.

바뀐 동작:
- **코드 확인 성공:** `POST /auth/signup/code/verify`, `/auth/password/code/verify`가 `{verified, verify_token}`을 돌려줍니다.
  - `verify_token`은 무작위 32바이트입니다. 원문은 저장하지 않고 해시만 `email_verifications.auth_code`에 `vt:`를 붙여 넣습니다. DB 구조는 바뀌지 않습니다.
- **가입·재설정:** `POST /auth/signup`, `/auth/password/reset`에 `verify_token`이 꼭 있어야 합니다(없으면 422).
  - 맞지 않으면 400(`INVALID_VERIFY_TOKEN`)으로 답합니다.
  - 쓰면 `auth_code='used'`로 바꿔 한 번만 쓸 수 있습니다. 조건부 UPDATE라 같은 토큰으로 동시에 보내도 한 번만 성공합니다.
- **이미 확인한 코드를 다시 확인:** 맞는 코드든 틀린 코드든 400(`CODE_ALREADY_USED`)으로 답하고, 토큰을 다시 주지 않습니다.
- 테스트 6개를 추가해 전체 63개입니다. 다른 사람이 끼어들어 가입·재설정하는 경우, 토큰 재사용, 인증 후 틀린 코드를 확인합니다.

## 평가표 API 규칙: 서버 소유자 확인 필수 (2026-11-16 결정)

- 화면은 평가표 번호를 주소(`?eval=`)에 드러내지 않습니다(`frontend/js/README.md`). 하지만 이것은 번호를 바꿔 보는 가벼운 시도를 줄이는 정도입니다. 번호는 요청에 실려 가고 개발자 도구로 바꿀 수 있습니다.
- 그래서 평가표 번호(`eval_no`)를 받는 모든 API는 **반드시 서버에서 소유자를 확인합니다.**
  - 대상: 상세 조회, 저장, 확정, 삭제, 서명, 공유, 엑셀 등
  - `eval_mst.email = 로그인한 사용자`(`current_user`)인 평가표만 다룹니다.
  - 남의 평가표, 휴지통의 평가표(목적에 따라)는 사업장 API와 같이 404로 답합니다. 남의 것인지 아닌지 구분해서 알려 주지 않습니다.
  - 평가표에 딸린 행(`eval_dtl`, `eval_action`, `eval_member`, `eval_sign` 등)을 다룰 때도 상위 평가표의 소유자를 먼저 확인합니다.
  - 각 API 테스트에 "다른 사용자의 평가표 번호로 요청 → 404" 경우를 꼭 넣습니다(`tests/test_workplaces.py`의 남의 사업장 테스트 참고).
- `eval_no`는 1씩 늘어나는 번호라 옆 번호를 짐작하기 쉽습니다. 추측하기 어려운 번호로 바꾸려면 테이블에 칸을 추가해야 하므로 팀 결정 후 진행합니다.

## 자동 테스트 안전장치 (2026-11-16 추가)

`tests/`는 저장소에 함께 두는 자동 테스트입니다. `.env`가 가리키는 DB에 테스트 데이터(`@test.invalid` 이메일, `T`로 시작하는 임시 업종 등)를 넣었다가 지웁니다. 그래서 아래 둘 중 하나일 때만 실행됩니다.

- DB 이름이 `_test`로 끝남 (예: `DB_NAME=safeT_test`). 테스트 전용 DB를 따로 둘 때 권장합니다.
- `.env` 또는 환경변수에 `ALLOW_DB_TESTS=1`. 개인 로컬 DB를 그대로 쓸 때만 씁니다.

둘 다 아니면 DB에 연결하지 않고 전부 건너뜁니다(`63 skipped`). 팀 공용·운영 DB를 가리키는 `.env`로는 실행하지 않습니다.

```bash
cd backend
# 개인 로컬 DB(safeT)에서 한 번만 돌릴 때 (PowerShell)
$env:ALLOW_DB_TESTS="1"; .venv\Scripts\python -m pytest -q; Remove-Item Env:ALLOW_DB_TESTS
```

위의 "### 테스트" 실행 방법은 이 조건을 갖춘 뒤에 동작합니다.

## API·화면 함께 실행

`python backend/run_local.py --demo --migrate` (저장소 루트).
기존 개인 개발 DB와 `.env`를 확인하고 평가표 추가 필드를 적용한 뒤 API·화면 서버를 실행합니다.
설정만 검사하려면 `--check`를 추가합니다. [실행·검사 안내](../docs/implementation/assessment-authoring.md#pc에서-한-번에-실행).

## 문서 다운로드 (위험성평가 결과서 PDF · 2026-11-17)

`GET /evals/{eval_no}/report` · 로그인 필요 · 내 평가표만(남의 것·휴지통은 404).

- 결과: `application/pdf` 첨부 파일. 파일 이름은 `평가명_위험성평가결과서.pdf`, 작성 중이면 `_미확정`이 붙습니다.
- 작성 중(W) 평가표도 내려받을 수 있고, 문서에 '미확정본'으로 표시합니다. demo로 만든 평가표는 '시험용 합성 자료'로 표시합니다.
- 요청할 때마다 새로 만듭니다. `eval_report`에 파일을 저장하는 부분은 파일 보관 위치가 정해진 뒤 연결합니다.
- 코드: `services/report_service.py`(값 모으기·PDF), `templates/report.html`(문서 모양), `routers/report.py`(API).
  참고 원본은 `dev_docs/report_service.py`, `dev_docs/report.html`(WeasyPrint 기준)입니다.
- PDF 엔진은 **xhtml2pdf**입니다. pip 설치만으로 Windows·Linux에서 같이 동작합니다(WeasyPrint는 Windows에 GTK가 필요).
- **한글 폰트가 필요합니다.** Windows는 맑은 고딕을 자동으로 씁니다. Linux 서버는 `apt install fonts-nanum`을 하거나, `.env`의 `REPORT_FONT_REGULAR`·`REPORT_FONT_BOLD`에 TTF 경로를 넣습니다. `.otf`(Noto CJK 등)는 읽지 못합니다. 폰트가 없으면 503 `REPORT_FONT_MISSING`을 돌려줍니다.
- 참고 원본과 다른 점: 가능성×중대성 판단 기준표와 가능성·중대성 열은 뺐습니다(판정 기준 팀 결정 전). '판단 필요'는 따로 세고 낮은 위험으로 보지 않습니다.

검사 (DB 없이):

```powershell
backend\.venv\Scripts\python -m pytest backend/unit_tests/test_report.py -q
```

## 참여자 서명 (SIGN · 2026-11-17)

로그인 필요 · 내 평가표만 · 확정(C·S·A)된 평가표에서만 동작합니다(작성 중이면 409 `EVAL_NOT_CONFIRMED`).

| 메서드·경로 | 설명 |
|---|---|
| GET /evals/{eval_no}/signs | 참여 근로자별 서명 여부·시각, 서명 수. 서명 이미지는 내려주지 않습니다 |
| POST /evals/{eval_no}/signs | `{member_no, confirm: true, sign_img: "data:image/png;base64,..."}` 저장 후 갱신된 현황 |

- 저장 위치: `eval_sign`(`signer_type='WO'` 참여 근로자, `confirm_yn='Y'`, `sign_yn='Y'`, `sign_img`, `sign_dt`).
- 참여 근로자마다 한 번만 저장합니다. 저장한 서명은 정정할 수 없습니다(다시 보내면 409 `ALREADY_SIGNED`).
- 전원이 서명하면 `eval_mst.sign_end_dt`를 기록하고 상태를 C → S(서명 완료)로 바꿉니다. 조치 완료(A)는 그대로 둡니다.
- 서명 이미지는 PNG data URL만 받습니다(약 220KB 이하). 문서 다운로드 PDF의 서명 칸에 이 이미지가 들어갑니다.
- 코드: `routers/sign.py`, `services/sign.py`, `schemas/sign.py`. 테스트: `tests/test_sign.py`(DB 필요).

## 개발 화면 서버 캐시 끔 (2026-11-17)

`run_local.py`의 화면 서버(8000번)를 `python -m http.server` 대신 `backend/dev_static_server.py`로 띄웁니다.
기존 서버는 캐시 금지 헤더가 없어, 브라우저가 고친 JS 대신 예전 파일을 그대로 쓰는 일이 있었습니다(서명이 화면에만 표시되고 저장되지 않음).
새 서버는 `Cache-Control: no-store`를 보내 항상 새 파일을 줍니다. 개발 확인 전용이며 운영 배포에는 쓰지 않습니다.
직접 띄울 때: `python backend/dev_static_server.py 8000 --directory frontend`

## 결과 공유 (SHARE · 2026-11-17)

참여자 전원이 서명한(`sign_end_dt` 있음) 확정 평가표만 공유할 수 있습니다(아니면 409 `SIGN_NOT_DONE`).

| 메서드·경로 | 로그인 | 설명 |
|---|---|---|
| GET /evals/{eval_no}/share | 필요 | 지금 쓸 수 있는 링크(없으면 `share: null`) |
| POST /evals/{eval_no}/share | 필요 | 링크가 없으면 만들고, 있으면 그대로 돌려줍니다(평가표당 1개, 7일) |
| POST /evals/{eval_no}/share/reissue | 필요 | 이전 링크를 막고 새 링크를 발급합니다 |
| POST /evals/{eval_no}/share/stop | 필요 | 공유 중지. 이전 링크는 바로 열리지 않습니다 |
| GET /share/{token} | 없음 | 받는 사람 화면용 평가표 정보 |
| GET /share/{token}/pdf | 없음 | 공유본 PDF. 다운로드 횟수만 +1 |

- 없는 링크, 중지된 링크, 만료된 링크는 모두 410 `SHARE_EXPIRED`("링크가 만료되었어요. 보낸 분께 다시 요청해 주세요.")로 같게 답합니다.
- 링크를 만들 때 `eval_report`에 공유본 기록(`sign_yn='N'`)을 남기고, `eval_share`에 토큰(24자 임의값)·만료일(7일)을 저장합니다.
- 공유본 PDF에는 서명 원본 이미지를 넣지 않고 서명 여부·시각만 표시합니다(화면설계서 29·30쪽). 내 평가표의 '문서 다운로드'는 서명 이미지를 포함합니다.
- 링크 주소는 `.env`의 `SHARE_BASE_URL`(받는 사람 화면 주소) 뒤에 `?t=토큰`을 붙여 만듭니다. QR 코드도 같은 주소로 서버에서 만듭니다(`segno`, SVG).
  휴대폰으로 QR을 찍어 보려면 `SHARE_BASE_URL`을 PC 내부 IP 주소로 바꾸고, 화면·API 서버도 그 주소로 열려 있어야 합니다.
- 링크를 열거나 내려받은 것은 결과 확인·서명으로 기록하지 않습니다.
- 코드: `routers/share.py`, `services/share.py`. 테스트: `tests/test_share.py`(DB 필요).

## DB 기준 평가

`python backend/run_local.py --catalog --migrate`로 실행합니다. 현재 조치와 개선대책 선택을 같은 함수로 계산하며 개선 후 값은 예상 결과입니다.

## 공동 위험 카드 DB

카드 원본 JSONL과 기기·위험요인 ID 대조표를 함께 적재합니다. 표의 기기 ID와 시나리오 ID는 기존 주 계약의 값을 사용합니다.

| 테이블 | 한 행의 단위 | 주요 열 |
| --- | --- | --- |
| `risk_card` | 근거 카드 한 건 | `evidence_id` 기본 키, 원본 `card_id`, 종류, 제목, 출처 코드·쪽, 검토 상태, 원본 JSON, 위험 태그, 미확정 시나리오 참조 |
| `risk_card_equipment` | 기기와 카드 한 쌍 | `equipment_id` + `evidence_id` 기본 키 |
| `risk_card_scenario` | 기존 시나리오와 카드 한 쌍 | `scenario_id` + `evidence_id` 기본 키 |

카드의 작업 정보, 설명, 대책, 대책 출처, 법령명은 `card_data`에 원본 구조로 보존합니다.
신규 카드는 `pending`으로 적재합니다. `NEW:`, `HOLD:`, `REF` 값은 미확정 참조에 담습니다. 법령명은 원본의 참고 값입니다.
카드와 연결은 근거 탐색용이며 기존 평가 카탈로그, 법령 레지스트리, 모델 입력에는 자동 반영하지 않습니다.

기존 `backend/.env`의 MariaDB 설정을 사용합니다. 저장소 루트에서 승인된 원본 경로를 지정합니다.
적재 명령이 [마이그레이션](migrations/20261119_risk_cards.sql)을 적용한 뒤 카드와 연결을 한 트랜잭션으로 저장합니다.
같은 자료를 다시 실행하면 신규 행이 생기지 않습니다. 같은 근거 ID의 원본이나 연결이 다르면 해당 적재를 중단합니다.

```powershell
python backend/import_risk_cards.py --cards "risk_card_data.md" --id-table "261119_기기_위험요인_ID표_v1_DR.md"
```

카드 열람 권한이 있는 팀 환경에서 `SAFET_RISK_CARDS_ENABLED=1`을 설정합니다. 로그인 후 `GET /rag/risk-cards?equipment_id=EQ_FRYER` 또는 `GET /rag/risk-cards?scenario_id=FRY`로 확인합니다. 두 조건을 함께 주면 둘 다 일치하는 카드를 반환합니다. 카드는 준비된 원본에서 적재하며 저장소에는 스키마와 코드만 둡니다.

가져오기 검사는 `python -m pytest backend/unit_tests/test_risk_card_import.py -q`로 실행합니다.

## AI 공통 기준 연결

`python backend/run_local.py --ai --migrate` 실행 및 서버 설정·테스트는
[AI 연결 통합](../docs/implementation/ai-integration.md)을 따른다.


### 실제 EXAONE 텍스트 초안 검사

`tests/live_text_ai_smoke.py`는 일반 자동 테스트에 포함되지 않으며, 명시 실행 시 실제 모델에 합성 텍스트와 서비스 프롬프트·카탈로그 후보를 전송합니다. 사진·SAM·SMTP는 사용하지 않습니다.
서버 AI 설정 및 이름이 `_test`로 끝나는 격리 DB 환경변수를 준비한 뒤 저장소 루트에서 실행합니다. 운영 DB는 사용하지 않습니다.

```powershell
$env:SAFET_RUN_LIVE_TEXT_TEST = "1"
python -m pytest backend/tests/live_text_ai_smoke.py -q
Remove-Item Env:SAFET_RUN_LIVE_TEXT_TEST
```

명확한 튀김 작업과 실제 사용 여부가 불분명한 사례를 검사합니다. 위험 후보·질문·조치 목록 저장, 답변 반영, 현재 위험도와 개선 후 예상 위험도 분리, 확정·재조회까지 검사하고 테스트 계정 자료를 정리합니다.
외부 모델 응답에 따라 실패할 수 있으므로 일반 회귀 테스트와 구분합니다. API 키는 `.env` 또는 서버 환경변수에만 설정합니다.

실제 실행 결과와 미해결 사항: [사진 없는 실제 AI 검토](../docs/implementation/live-text-ai-review-20261118.md).


### AI 실패 후 화면 복구 검사

격리 `_test` DB 환경에서 `python backend/unit_tests/browser_catalog_smoke.py --ai-fixture`를 명시 실행합니다(Playwright·Edge 필요). 외부 AI 대신 모의 응답을 사용하지만 로컬 API·DB·공통 계산·브라우저는 실제 실행합니다. 모델 요청 실패, 토큰 계수 실패, 입력 한도 초과 뒤 답변과 문서 보존 및 재시도·확정까지 검사합니다.

팀 영향 범위: [화면·문서 담당자 인계와 오프라인 검증](../docs/implementation/team-handoff-20261118.md).

## 평가표 삭제·휴지통 (H02 · C02 · 2026-11-17)

로그인 필요 · 내 평가표만 · **작성 중(W) 평가표만** 삭제할 수 있습니다(확정·서명된 평가표는 409 `EVAL_LOCKED`, 법정 기록 보존).

| 메서드·경로 | 설명 |
|---|---|
| DELETE /evals/{eval_no} | 휴지통으로 옮깁니다(`del_yn='Y'`, `del_dt`). 내 평가표 목록·편집 화면에서 빠집니다 |
| GET /trash | 휴지통 목록과 남은 일수(`days_left`). 30일 지난 평가표는 이때 영구 삭제합니다 |
| POST /trash/{eval_no}/restore | 복원(`del_yn='N'`). 이전 입력 그대로 작성 중으로. 30일이 지났으면 410 `TRASH_EXPIRED` |
| DELETE /trash/{eval_no} | 영구 삭제. 복원할 수 없습니다 |

- 영구 삭제는 평가표와 딸린 행(`eval_action`, `eval_file`, `risk_event`, `eval_share`, `eval_sign`, `eval_report`, `eval_dtl`, `eval_machine`, `eval_member`)을 참조 순서대로 지웁니다.
- 30일 자동 삭제는 별도 예약 작업 없이 휴지통 목록을 열 때(그리고 만료된 평가표를 복원하려 할 때) 실행합니다. 운영에서 정확한 시점이 필요하면 예약 작업을 따로 둡니다.
- 코드: `routers/trash.py`, `services/trash.py`. 테스트: `tests/test_trash.py`(DB 필요).

## 휴지통 만료 삭제·복원 동시 요청 (2026-11-18)

휴지통 목록을 열 때 하는 만료 삭제(`services/trash.py` `_purge_expired`)가 만료 대상을 `FOR UPDATE`로 잠그면서 고릅니다.
전에는 잠그지 않고 골라서, 만료 경계에서 복원과 겹치면 복원 성공 응답이 나간 평가표가 지워지거나(innodb_snapshot_isolation OFF: 이전 MariaDB·MySQL) 목록이 1020 오류로 실패했습니다(ON: MariaDB 11.6.2+ 기본).
지금은 복원이 먼저 커밋되면 만료 삭제에서 빠지고, 만료 삭제가 먼저 잠그면 복원은 기다렸다가 404를 받습니다.
검사: `tests/test_trash.py`의 `test_만료_경계_*` (두 DB 연결, snapshot isolation ON·OFF 각각).


## 8010 관문 연결

`SAFET_AI_GATEWAY_URL`을 설정하면 텍스트·사진 모두 같은 관문과 `SAFET_AI_API_KEY`를 사용합니다. 현재 관문은 토큰 계수 경로가 없어 초안 생성이 차단됩니다. [확인 결과와 서버 보완 사항](../docs/implementation/gateway-integration-20261118.md)을 참고하세요.


## 동시 저장·AI 잠금·사진 캐시 보완

초안 생성·위험 추가·질문 답변은 DB 읽기 트랜잭션 종료 후 AI를 호출하고 저장 직전에 변경 여부를 다시 확인합니다. 사진 탐지 결과는 기존 상태 JSON에 보관하여 같은 사진을 반복 호출하지 않습니다. 관련 검사는 격리 `_test` DB에서 `python -m pytest backend/tests/test_ai_review_regressions.py backend/unit_tests/test_catalog_ai.py -q`로 실행합니다. 모의 AI를 사용하며 실제 서버를 호출하지 않습니다.

[변경 범위와 검토 사항](../docs/implementation/review-fixes-20261118.md)

N02·N08 문맥 확장 설정·검수: [설명](../docs/implementation/n02-n08-context-expansion.md). 환경변수 SAFET_RAG_CONTEXT_DIR을 지정하면 별도 검수 문맥을 추가하고, 미설정 시 기존 검색을 유지합니다.
