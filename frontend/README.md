# 프런트엔드

상태: HTML·CSS·JavaScript 화면 개발을 위한 폴더와 안내만 준비했습니다. 실행 가능한 화면은 후속 작업입니다.

| 경로 | 역할 |
|---|---|
| [pages/](pages/README.md) | 기능별 HTML 화면 |
| [css/](css/README.md) | 공통·화면별 스타일 |
| [js/](js/README.md) | 화면 동작·API 호출 |
| [public/](public/README.md) | 로고·아이콘·공용 이미지 |

먼저 전체 화면 이동·공통 UI·합성 데이터 표시를 구현합니다. 파일 이름은 `basic.html`, `basic.css`, `basic.js`처럼 맞춥니다.
실제 HTML이 아직 없으므로 현재 실행 명령은 없습니다. 화면 뼈대 PR에 실행 방법을 추가합니다.

서비스 데이터 저장과 권한 검사는 백엔드에서 수행합니다.
AI 추천값과 사용자가 선택한 값을 구분하며, 정보 부족을 낮은 위험으로 표시하지 않습니다.
API 연결 전에 [공통 JSON](../contracts/README.md)을 맞춥니다.
공통 CSS·API 호출 코드 변경은 작업자와 먼저 조율하고, 세부 담당자는 Issue에서 정합니다.
