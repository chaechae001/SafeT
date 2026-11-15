# 구성과 데이터 흐름

작성일: 2026-11-13, Asia/Seoul.
상태: 저장소 구성 초안. 프런트엔드·백엔드·서비스 AI는 미구현이다.

## 연결 방향

```text
사용자 → 프런트엔드 → 백엔드 → AI
                       ↓       ↓
                 검토·개선 이력  분석 초안
```

프런트엔드는 입력과 결과를 표시한다.
백엔드는 권한·파일·분석 요청·검토 결과를 관리한다.
AI는 분석 초안을 반환한다. 최종 안전 판단은 담당자가 한다.

업종별 저장소는 현재 만들지 않는다. 치킨 전문점 실험을 기존 AI 경로에서 관리한다.
다음 업종의 분류 체계와 자료 구조는 실제 요구가 생길 때 정한다.
모델 분리 방식, GPU 배포 방식과 데이터베이스는 이 작업에서 확정하지 않았다.

## 검토할 경계

- AI 원본 결과와 사용자 수정 결과를 구분한다.
- 미평가·정보 부족·실행 실패를 구분한다.
- 검색 자료는 관찰 사실과 구분한다.
- 법적 의무와 실무 권고를 구분한다.
- 다른 매장의 파일과 이력에 접근하지 못하게 한다.

## 협업과 관리자 작업

기능 브랜치에서 작업하고 PR로 검토한다.
폴더·문서·워크플로 파일 추가는 쓰기 권한으로 처리할 수 있다.
브랜치 보호 설정은 관리자에게 요청한다.

권장 main 설정: PR 승인 1명, CPU checks 통과, 강제 푸시·삭제 차단.
저장소 요금제와 관리자 권한을 확인한 뒤 적용한다.
이번 작업에서는 보호 설정을 적용하지 않았다.

참고·조회일: 2026-11-13.
- [GitHub 브랜치 보호](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
- [checkout 공식 사용법](https://github.com/actions/checkout)
- [setup-python 공식 사용법](https://github.com/actions/setup-python)

요구사항과 팀 결정의 원본은 [공식 Safe-T Notion](https://app.notion.com/p/Safe-T_-409a5d647ec5806ba57df6e84f77d545)이다.
이 문서는 새로운 팀 결정을 확인한 기록이 아니다.
