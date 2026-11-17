# Python 3.11 통일 — 환경 목록과 SAM 3 연결 방식 (2026-11-17)

- 결정 출처: **사용자 전달**(2026-11-17, "팀은 3.11을 쓰기로 통일"). 팀 문서·노션에서 근거 파일은 찾지 못했다.
  - 문서에 나온 '3.11'은 로컬 실행 기록의 Python 3.11.9뿐이었다(RAG 지식베이스 작업기록 v1·v2).
- 예외: SAM 3(`sam3` 패키지)는 Python 3.12 이상을 요구한다. 그래서 3.12 환경으로 따로 두고, 본체와는 JSON 파일로만 연결한다.

## 환경 목록

| 환경 | 이전 | 3.11 대상 | 핵심 패키지 | 검증 | 고정 파일 |
|---|---|---|---|---|---|
| Cloud EXAONE 3.5 + LangGraph | `/home/elicer/venvs/e35-vllm` (3.10.14) | `/home/elicer/venvs/e35-vllm-py311` (3.11.18, uv 관리) | vllm 0.10.1.1, torch 2.7.1+cu126, transformers 4.55.4, huggingface-hub 0.36.2, xgrammar 0.1.21, langgraph 1.2.22 | enum 재현 25/25 출력 동일(3.10 대비), 그래프 vLLM 실행 계약 오류 0 | `e35-vllm-py311.requirements.txt` |
| Cloud SAM 3 (예외) | `/home/elicer/venvs/det-sam3` (3.12.16) | 유지(3.12) | sam3 @ git eef6839, torch 2.7.1+cu126, timm 1.0.31 | 사진 3장 탐지 정상, 결과 JSON을 3.11 그래프가 읽음 | `det-sam3-py312.requirements.txt` |
| 로컬 파이프라인(`run_all.sh`) | uv 기본 Python 3.13.13 | uv 관리 cpython 3.11.15 | jsonschema 4.26.0, langgraph 1.2.22, openpyxl 3.1.5 | ALL PASS, 산출물이 3.13 결과와 같음(시각·ID·경로 제외) | `local-pipeline-py311.requirements.txt` |
| Cloud Qwen(`safet-venv`), YOLO(`det-yolo`), OCR(`safet-ocr-venv`) | 3.10.14 | **미사용(전환 안 함, 사용자 결정 2026-11-17)** | — | 해당 없음. 기존 venv 보존 | — |

- 3.10 freeze 원본은 `cloud_raw/`에 있다. 3.10과 3.11의 패키지 목록(177개)은 같다.
- 기존 venv는 수정·삭제하지 않았다.

## 로컬에서 3.11로 실행하는 방법

Windows 사용자 이름에 한글이 있으면 시스템 Python 3.11.9 + `uv run --with`가 시작 단계에서 멈춘다. `.pth` 파일을 cp949로 읽다가 `UnicodeDecodeError`가 난다(3.13은 문제없음). 다음처럼 uv 관리 Python과 캐시를 ASCII 경로에 둔다.

```bash
export UV_PYTHON=3.11 UV_PYTHON_PREFERENCE=only-managed UV_PYTHON_INSTALL_DIR=C:/Users/Public/uvpython UV_CACHE_DIR=C:/Users/Public/uvcache_py311
uv python install 3.11
bash run_all.sh
```

`run_all.sh` 자체는 바꾸지 않았다(공용 파일). 버전을 고정하려면 팀 확인 후 `.python-version` 또는 `run_all.sh`에 반영한다.

## SAM 3(3.12) ↔ 본체(3.11) 연결 형식

1. SAM 3 단계(det-sam3, 3.12): `detect_compare_v2.py --model sam3 --inputs DIR --out sam3_detections.json`. 출력은 탐지 v2 초안 형식이다. `model_output.request_id/status/photos/detections[{detection_id, photo_id, equipment_id, confidence, bbox}]`
2. 프로세스 종료와 GPU 메모리 반환을 확인한다(100 MiB 미만). 두 모델을 동시에 올리지 않는다.
3. 본체 단계(3.11): `cloud/py311/run_graph_detfile.py`가 JSON을 읽어 그래프 입력 `detection`으로 바꾼다. 기기마다 최고 점수 1건을 넘긴다: `{detection_request_id, status, items[{detection_id: "photo#d", equipment_id, confidence}]}`. 이후 사람 확인(interrupt) → 검색 → EXAONE → 계약 검증 → 사람 선택 → 위험도 규칙 순서로 진행한다.
- 두 환경은 같은 프로세스에서 import하지 않는다. Python 객체(pickle)는 넘기지 않는다.

## 알려진 문제(해결)

- vLLM 종료 멈춤: `hitl_graph.py`에 `VllmBackend.close()`(engine_core.shutdown, atexit)가 추가되었다. `run_graph_detfile.py`는 `hg.close()` 후 `os._exit`로 끝난다. 2026-11-17 01:46~01:48 Cloud 재실행에서 exit 0, 종료 0.6초 뒤 GPU 5 MiB로 돌아왔다.

## 팀 저장소 반영

- `chaechae001/SafeT`(로컬 `Documents/codes/SafeT`, 브랜치 `chore/python311-sam3-exception`, 커밋·푸시 안 함): `.python-version`(3.11) 추가. README.md, ai/README.md, docs/structure.md에 SAM 3 예외 문구를 넣었다.
