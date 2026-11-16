# 치킨집 현재/개선 후 예상 위험도 실험

기준 버전: `CHK-3L-EXP-0.1`. 사람의 구조화된 판단 입력을 일관된 규칙으로 분류합니다. 사진·문장에서 위험도를 추론하는 모델이나 법령 자동 판독기는 아닙니다. 기존 모바일 화면/API/DB에는 아직 연결하지 않았습니다.

## 실행 (저장소 루트)

Python 3.11 이상, 추가 패키지·Docker·API 키 없이 실행합니다.

```bash
python -m ai.risk_rules --check
python -m unittest discover -s ai/risk_rules/tests -v
python -m ai.risk_rules --case-id C01 --json
```

Windows에서는 `python` 대신 `py -3.11`을 사용할 수 있습니다. GitHub 웹에서 PR의 Files changed로 기준을 검토하고 Checks에서 자동 검사 결과를 봅니다. 직접 실행하려면 이 브랜치를 체크아웃하세요.

```bash
git fetch origin
git switch --track origin/feat/chicken-risk-rules-v0.1
```

이미 로컬 브랜치가 있으면 `git switch feat/chicken-risk-rules-v0.1`만 사용합니다. 작업 중인 파일이 있다면 먼저 저장·커밋하고 전환합니다.

## 내 판단과 비교

1. `examples.json`을 별도 파일로 복사합니다. 사례 ID는 중복 없이 입력합니다.
2. `current.facts`에 실제 관찰·확인 근거를 기록합니다. 계획된 조치는 넣지 않습니다.
3. 확인 불가한 boolean은 `null`, 법정조치와 통제는 `unknown`, 핵심 정보 부족은 `complete: false`로 입력합니다.
4. `expected`에 팀원이 규칙 실행 전 독립적으로 판단한 현재/예상 코드(R/Y/G/N)를 입력합니다.
5. 개선계획이 있으면 `projection`에 예상 상태, 대책, 작동 가정, 효과 이유, 실행 후 확인 절차를 기록합니다. 사람의 효과 가정 검토 후에만 `effect_reviewed: true`로 둡니다.
6. `python -m ai.risk_rules --cases <내사례.json> --check --json`으로 비교합니다. 불일치 시 종료코드 1, 형식 오류 2입니다. 기대값을 결과에 맞춰 덮어쓰지 말고 판단 근거를 먼저 검토하세요.

`--check`의 일치율은 규칙 회귀검사이며 현장 정확도가 아닙니다. 포함된 15건은 전부 합성 사례입니다. 실제 검증에서는 독립 검토자의 정답, 등급별 혼동행렬, 상→하 과소평가와 미판정 비율을 별도로 기록해야 합니다.

## 입력 정의

| 필드 | 의미 |
|---|---|
| facts | 현재는 관찰·기록 근거, 예상은 미래 상태의 명시적 가정 |
| complete | 판정에 필요한 핵심 정보가 충분한지 |
| severe_residual | 해당 상태의 조치를 고려해도 사망·영구장해로 이어질 위험 경로가 남는지 |
| treatment_residual | 치료가 필요한 부상·질병 위험이 남는지 |
| unresolved_near_miss | 같은 위험 경로의 아차사고 원인이 미해결인지 |
| legal_status | compliant / noncompliant / unknown / not_applicable. 특정 적용 의무를 검토한 범위의 값이며 사업장 전체 준법 인증 아님 |
| controls | effective / partial / ineffective / unknown / not_needed. 해당 위험 통제 효과 |
| addressed_flags | 해소를 가정한 SEVERE / LEGAL / TREATMENT / NEAR_MISS / CONTROLS와 대책 연결 |

`not_applicable`, `not_needed`는 검토를 생략하는 기본값이 아닙니다. 실제 사례에는 이유를 facts에 남겨야 합니다. 효과 검토 체크는 사람의 근거 검토 진술이며 프로그램이 그 진실성을 검증하지 않습니다.

규칙 수정은 `engine.py`와 `criteria.json` 버전을 함께 변경하고 테스트를 갱신하세요. JSON만 수정하면 동작이 바뀌지 않습니다. 출력에 입력·규칙 파일·엔진 SHA256을 남깁니다.

- [판단 기준서](../../docs/risk/chicken-risk-3level-experiment-v0.1.md)
- [근거 자료와 확인 범위](../../docs/risk/sources.md)
- [합성 테스트 사례](examples.json)

## 다음에 팀과 공유할 자료

익명화한 작업·기기·위험 경로, 현재 조치와 유효성 근거, 아차사고 기록, 적용 법령 조문과 적용 이유, 대책별 효과 가정, 독립 검토자의 현재/예상 등급과 이유를 공유하세요. 실제 조치 후 확인 결과는 예상값과 별도로 저장해야 합니다. 개인정보·현장 원본 사진·API 키·DB 덤프·권한 없는 원문 PDF는 이 실험 PR에 포함하지 않습니다.
