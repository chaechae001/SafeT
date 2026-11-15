# Safe-T AI 모델 실험 코드

선별일: 2026-11-13 (한국 시간).
대상: chaechae001/SafeT의 첫 AI 코드 공유.
범위: 로컬에 내려받은 Cloud 작업 사본. 현재 Cloud 파일과의 최신 일치 여부는 미확인이다.
원본 실험 코드는 수정하지 않았다. 모델 가중치와 원본 데이터는 Cloud에서 별도로 관리한다.

## 선택한 파일

| 폴더 | 코드 | 목적 |
|---|---|---|
| ai/experiments/261111_franchise_training_v3_DR | 261111_train_v3_DR.py | NF4 기본 모델·RAG·QLoRA 비교 실험 |
| ai/experiments/261112_model_selection_DR | 261112_compare_models_DR.py | 모델별 추론·평가 |
| 같은 폴더 | 261112_run_comparison_DR.py | 모델 다운로드와 비교 실행 순서 관리 |
| ai/experiments/261112_single_vs_pipeline_DR | 261112_benchmark_DR.py | 단일 모델과 단계별 파이프라인 비교 |
| 같은 폴더 | 261112_resume_ocr_DR.py | OCR 호환성 수정과 재개 |
| 같은 폴더 | 261112_recover_ocr_DR.py | 실패한 OCR 실행 복구 |
| 같은 폴더 | 261112_minimal_image_probe_DR.py | 최소 이미지 입력 점검 |

설정 5개도 포함했다. 모델 ID·revision, 실행 조건·프롬프트, 학습 프로토콜, 분류 체계, 텍스트 모델 정보를 보존한다.
폴더 이름과 파일 이름을 유지했다. benchmark가 이웃 폴더의 compare_models를 동적으로 불러오기 때문이다.
현재 제공 범위는 실험 코드이다. 서비스 추론 API와 백엔드 연결은 구현되지 않았다.

## 전체 실행 전에 해결할 항목

- 각 실험의 frozen 입력·정답·이미지와 학습 references, evidence는 이 묶음에 포함하지 않았다. 데이터 공유 권한을 먼저 확인해야 한다.
- 학습 코드에는 261111_evidence_DR.jsonl과 references/train.jsonl, development.jsonl, test.jsonl 등이 필요하다.
- 비교 실행에는 frozen/inputs.json, references.json, taxonomy.json, hashes.json과 이미지가 필요하다.
- 파이프라인에는 frozen 데이터·evidence.json 등이 필요하다. 원본 JSON에 기록된 Cloud 이미지 경로도 유효해야 한다.
- OCR 코드는 /home/elicer/safet-ocr-venv/bin/python을 사용한다. 복구 스크립트는 기존 Cloud 실험 경로를 assert로 확인한다. 다른 폴더에서 실행하면 중단한다.
- OCR 복구·재개 코드는 기존 결과를 이동하거나 이어 쓸 수 있다. 기존 결과가 있는 폴더에서 임의로 실행하지 않는다.
- GPU 실행 환경과 OCR 실행 환경은 별개이다. observed_environment JSON은 확인된 버전 기록이며 설치용 lock 파일이 아니다.
- OCR은 PaddleOCR/PaddleX와 opencv-contrib-python-headless 4.10.0.84의 호환성 처리가 있다. OCR 환경 전체 버전과 재설치 방법은 추가 확인이 필요하다.
- 학습 코드는 모델 캐시를 local_files_only=True로 읽는다. 지정 revision의 모델을 먼저 준비해야 한다.
- 기존 결과를 보존하는 장치가 있다. 재실행은 새 실행 폴더와 별도 데이터 복사본에서 한다.

## 제외 및 보류

- 동일 해시의 중복 코드와 original 이름의 과거 시도본은 제외했다.
- 제조업 자산 삭제 스크립트는 제외했다.
- 로컬 데이터 준비, Windows 글꼴 의존, 수집·전송·보고서 생성 도구는 별도 검토로 보류했다.
- 메모리 탐색·추가 실험·RAG 자료 축적 코드도 별도 검토로 보류했다. 필요하지 않다는 뜻은 아니다.
- 모델 가중치, 어댑터, 원본 데이터, 이미지, 영상, 가상환경, 실행 로그는 복사하지 않았다.
- 업로드한 12개 원본 파일의 해시는 selection_manifest JSON에 있다.

## 검증

코드 7개의 Python 구문을 분석했다. 설정 JSON 5개를 읽었다.
선택 파일 12개는 원본과 SHA-256 해시가 일치한다.
train_v3, compare_models, benchmark의 --self-test가 모두 통과했다.
이 검사는 파싱·지표 계산 등의 로직 검사이다. GPU 추론·학습·OCR 실행 검사는 아니다.
자격증명 패턴 검사에서 선택 파일의 일치 항목은 0개이다. 완전한 비밀정보·개인정보 검수를 뜻하지 않는다.
세부 결과는 validation JSON에 있다.

## 한계와 다음 작업

합성 사례와 AI 보조 정답을 독립 현장 평가로 취급하지 않는다. 최종 안전 판단은 담당 전문가가 한다.
다음 작업은 Cloud 최신본 대조, 데이터 연결, 경로 설정 분리, 실행 환경 복원 순서로 진행한다.
그 뒤 서비스에서 사용할 모델과 요청·응답 형식을 확정하고 추론 API를 연결한다.

## 팀원용 확인 방법

저장소 루트에서 다음 검사를 실행한다. 모델 다운로드나 GPU 실행은 하지 않는다.

```bash
python ai/experiments/261111_franchise_training_v3_DR/261111_train_v3_DR.py --self-test
python ai/experiments/261112_model_selection_DR/261112_compare_models_DR.py --self-test
python ai/experiments/261112_single_vs_pipeline_DR/261112_benchmark_DR.py --self-test
```

위 명령은 Python 표준 라이브러리만 사용한다. 전체 추론에는 Linux·CUDA 환경과 별도 패키지·데이터가 필요하다.
학습 코드는 텍스트 분류 적응 실험이다. 사진 기반 위험 탐지 모델 학습으로 해석하지 않는다.
