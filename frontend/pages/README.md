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
