# 화면별 HTML

로그인·회원가입·사업장·기본정보·현장입력·기기·초안·상세·결과·서명·공유 화면을 둡니다.

- 예: `login.html`, `basic.html`, `field.html`, `equipment.html`, `draft.html`, `risk.html`, `result.html`.
- 화면별 스타일과 JavaScript는 `../css/`, `../js/`에 같은 이름으로 둡니다.
- 화면 이동과 합성 데이터 표시부터 구현합니다. 실제 API 연결은 후속 작업입니다.

## 화면 파일 목록 (2026-11-16 추가)

jQuery로 화면을 전환할 예정이라, 한 흐름의 화면을 파일 하나에 `view` 섹션으로 합쳤습니다. 첫 view가 처음 화면입니다.

| 파일 | view id · 화면 ID | CSS |
|---|---|---|
| [login.html](login.html) | `v-login` A01 로그인 · `v-signup` A02 회원가입 | auth |
| [workplace.html](workplace.html) | `v-list` B01 사업장 관리 · `v-new` B02 등록 · `v-edit` B02-E 수정 | workplace |
| [home.html](home.html) | `v-home` H01 내 평가표 | home |
| [trash.html](trash.html) | `v-trash` H02 휴지통 | common |
| [write.html](write.html) | `v-basic` S01 기본정보 · `v-field` S02 현장입력(`#help` S02-G) · `v-equipment` S03 보유기기 · `v-generating` S04 초안 생성 | field |
| [draft.html](draft.html) | `v-list` S05·S05-A 리스트(`#confirm` S05-E, `#delete` C02) · `v-input` S05-B 입력 필요 모드 · `v-risk` S06·S06-P 위험 상세 · `v-risk-green` S06-G 초록 항목 · `v-bulk` S05-C 일괄 지정(`#assign` S06-D) · `v-add` S07 · `v-add-select` S07-C · `v-saving` S05-D | draft, risk, bulk-assign |
| [result.html](result.html) | `v-list` S08 확정된 평가표 · `v-detail` S08-D 읽기 전용 상세 | result, risk |
| [sign.html](sign.html) | `v-pick` SIGN ① 참여자 선택 · `v-draw` SIGN ② 서명 | sign |
| [share.html](share.html) | `v-share` SHARE 결과 공유(`#qr`, `#reissue`) | share |
| [share-download.html](share-download.html) | `v-download` 받는 사람 PDF 다운로드(로그인 없음) | share |

- 위 예시의 `basic.html`·`field.html` 같은 단계별 파일 대신 `write.html` 한 파일에 단계를 모았습니다.
- 부록의 후속업무(F01·F03·F03-L·F03-R)와 지난 평가 가져오기(41쪽)는 "협의 중·향후" 항목이라 만들지 않았습니다.
- `name` 속성은 테이블 정의서 V1.1의 컬럼명을 따릅니다. `biz_code`·`machine_code` 같은 코드값은 합성 값이므로 기준 데이터가 확정되면 바꿉니다.

## jQuery 연결 후 바뀐 점 (2026-11-16 추가)

- `draft.html`의 `v-input`(S05-B)과 `v-risk-green`(S06-G)은 `v-risk` 하나로 합쳤습니다. 화면설계서 17쪽의 "입력 필요 모드는 기존 위험 상세를 재사용"에 맞춰, `draft.js`가 같은 화면을 모드(전체/입력 필요)와 신호(초록 탭 포함)에 따라 채웁니다.
- `draft.html` 화면 목록: `v-list` · `v-risk` · `v-bulk`(`#assign`) · `v-add` · `v-add-select` · `v-saving`.
- 회원가입 후에는 `workplace.html?first=1#v-new`로 이동합니다. 첫 등록이라 취소 버튼이 없습니다.
- JS 없이 열면 주소 `#view-id`로 화면을 볼 수 있습니다. JS가 켜지면 화면 전환은 `common.js`가 맡습니다.

## 진입 화면·오류 페이지 (UX-001 · 2026-11-21)

- `login.html`을 주소만으로 열면 스플래시(탭마다 한 번) 뒤 시작 화면 `#v-start`(로그인/회원가입 선택)가 나옵니다. `?required=1`·`?expired=1`·`?logout=1`이나 `#v-login` 등 해시가 있으면 기존처럼 바로 해당 화면입니다.
- 회원가입·비밀번호 재설정은 대·소문자·숫자·특수문자 포함 8자 이상이어야 합니다. 화면(입력 중 조건 표시)과 서버 API(`schemas/auth.py`) 모두 검사합니다(UX-002). 기존 계정 로그인에는 적용하지 않습니다.
- 아이디(이메일) 저장은 이 기기 브라우저의 `localStorage`(`safet.rememberEmail`)에만 저장합니다. 비밀번호는 저장하지 않습니다.
- `error.html`: 오류 안내 페이지. 개발용 화면 서버(`backend/dev_static_server.py`)가 404·405·5xx와 폴더 주소에 이 페이지를 같은 상태 코드로 보내고, 루트(`/`)는 `login.html`로 보냅니다. 직접 확인: `error.html?code=500`. 운영 서버 연결은 배포 방식 결정 후입니다.
- API 오류(5xx 등)는 입력 내용을 지키기 위해 페이지를 바꾸지 않고 기존처럼 화면 안에서 안내합니다.

## 초안·작성·내 평가표 화면 수정요청 반영 (UX-004~006 · 2026-11-21)

- `body[data-ux-guide]` 페이지(workplace·home·draft)는 `js/ux-guide.js`·`css/ux-guide.css`로 입력 안내(자동 포커스·다음 칸 강조)와 달력 연도·월 선택을 씁니다. 다른 페이지의 달력은 그대로입니다.
- home: 처음 탭 전체, 목록만 스크롤(`#home-scroll`), 카드 제목은 화면에서만 날짜·'위험성평가'를 뺌.
- draft: 고정 영역(제목·요약·필터) + 스크롤 영역(`#draft-scroll`), 항목 삭제, '입력 내역 저장'은 지금 항목만, 담당자·예정일은 팝업(`#assign`을 body로 옮겨 재사용).
- write: `js/voice-recorder.js`가 '음성' 버튼을 녹음기(상태·타이머·소리 막대·최대 5분·다시 듣기·삭제)로 바꿉니다. 녹음 파일은 서버로 보내지 않고 전사문만 저장합니다.
