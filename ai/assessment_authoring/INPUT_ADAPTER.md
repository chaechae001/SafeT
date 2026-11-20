# 입력 어댑터 연결과 검사

Python 3.11 이상과 기존 [백엔드 의존성](../../backend/requirements.txt)을 사용한다. 저장소 루트에서 실행한다. Linux·macOS는 `PYTHONPATH=backend`를, PowerShell은 `$env:PYTHONPATH = 'backend'`를 먼저 설정한다.

```bash
python contracts/assessment_authoring/v1/validate.py
python -m unittest ai.assessment_authoring.tests.test_input ai.assessment_authoring.tests.test_detection -v
python -m pytest -q backend/unit_tests/test_catalog_ai.py
```

Windows에서 계약 참조 파일의 SHA-256이 다르면 Git checkout의 줄바꿈 설정을 확인한다. 계약 검사는 저장소의 LF 바이트를 기준으로 한다.

## 호출

```python
from ai.assessment_authoring.input_adapter import build_context

context = request.model_dump()
context["machines"] = workplace["machines"]
bundle = build_context(context)
```

- 서버의 `CreateAssessment` 또는 위 입력 사전을 받는다. 사업장 기기와 서버 캐시를 사용하려면 사전으로 전달한다. API에서 정규화하기 전의 공백까지 보존하려면 서비스가 원문 문자열을 전달해야 한다.
- 사진과 함께 `detection_result`를 지정하면 고정 SAM 응답 또는 기존 `detect_equipment` 반환값을 사용한다. 이 경로는 외부 호출과 캐시 갱신을 생략한다. 입력의 사진 순서가 `PHOTO1`, `PHOTO2`의 기준이다.
- 사진이 있고 결과가 생략되면 기존 `make_input`을 통해 SAM 탐지와 임계값 설정을 사용한다. 같은 사진·순서·위치·임계값·탐지 주소에서는 서버 캐시를 재사용한다. 같은 주소에서 모델이나 클래스 설정을 바꿀 때는 `_refresh_photos`로 다시 탐지한다.
- 성공 캐시 `context["_photo_cache"]`에는 원본 탐지 박스·점수·모델 메타데이터, 사진별 표준 기기 ID, `unmapped` 목록이 남는다. 서버에서만 캐시를 받아 저장한다. 통합 파이프라인은 요청 사전을 복사하므로 캐시 저장이 필요할 때는 서비스가 먼저 `build_context(context)`를 호출하고 만든 Bundle을 넘긴다.
- 빈 입력·잘못된 사진·탐지 실패는 기존 `AuthError` 처리 경로를 사용한다. 실패 시 사용자 입력과 기존 캐시는 유지된다. 재시도는 호출자가 결정한다. DB 작업만 고르는 기존 수동 평가는 기존 서비스 경로에서 처리한다.

## 제출 예시

- [텍스트](fixtures/input/text/input.json), [음성 전사](fixtures/input/voice/input.json), [사진](fixtures/input/photo/input.json), [혼합](fixtures/input/mixed/input.json), [사업장 기기](fixtures/input/inventory/input.json), [탐지 0건](fixtures/input/zero_detection/input.json)
- [기기 매핑](fixtures/input/equipment_mapping.json), [고정 SAM 응답](fixtures/input/sam_response.json), [미등록 목록](fixtures/input/unmapped.json), [오류 응답](fixtures/input/errors.json)

표준 ID 42개는 공통 계약 목록에서 제한한다. 모델이 준 등록 ID를 우선 사용한다. ID가 비어 있으면 기존 클래스 대응표의 열린 어휘 프롬프트와 직접 대응 클래스를 정확히 대조한다. 기존 서비스 예시의 `deep fryer`와 `shelf`도 허용한다. 명시된 미등록 ID는 별도 기록한다. 사업장 기기는 DB 기기 코드 또는 기존 기기 마스터의 이름·별칭을 사용한다.

사진마다 기기별 최고 탐지 점수 한 건을 요약한다. 기기 후보와 사업장 보유 정보는 각기 다른 입력 유형으로 기록한다. 사진별 위치는 요청의 입력 위치다. 작동 여부와 안전조치 실행 여부는 별도 근거가 필요하다.

합성 사례로 입력 정리·오류·사진별 중복·캐시를 검증했다. 기존 SAM 호출은 HTTP 모의 응답으로 검사했다. 실제 사진에서의 오탐·미탐과 모델 응답 시간은 별도 검증이 필요하다.
