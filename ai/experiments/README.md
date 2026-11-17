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

## HITL 추천 구조 기반 자료 (2026-11-17 추가)

추가일: 2026-11-17 (한국 시간). 작성: DR.
방향: Human-in-the-Loop(사람 검토 기반 AI) 구조. 사진 분석은 기기 식별만 하고, LLM은 기기별 위험요인 후보를 추천한다. 위험도는 규칙으로 계산하고, 최종 선택과 판단은 사용자가 한다.
로컬 작업 폴더에서 허용 목록 파일만 복사했다. 폴더 이름은 로컬과 같다. 이웃 폴더를 상대 경로로 참조하기 때문이다.

| 폴더 | 내용 |
|---|---|
| 261115_AI출력계약_신호기준_DR | v1(신호 기준) 계약, v2(HITL) 스키마 7종, v2.1(위험도를 백엔드 정책으로 변경) 스키마·예시와 생성 스크립트 |
| 261115_기기마스터_인식평가셋_DR | 음식점 기기 마스터 42종, 기기 인식 출력 스키마, 생성·검증 스크립트 |
| 261115_RAG_지식베이스_DR | 기기-위험요인 인덱스·청크 생성 스크립트, 법령 목록, 점검 결과 요약, 작업기록 |

### 제외한 자료

- 평가 정답: 위험요인 추천 정답셋 v2·v3, v3 검수표·holdout 목록, 기기 인식 평가셋·라벨, 검수 필요 목록.
- 원문 PDF, 페이지 캡처, 현장 사진, API 키·토큰.
- 생성 스크립트의 로컬 절대 경로는 `<LOCAL_WORKSPACE>`, `<LOCAL_SCRATCH>`로 바꿨다. 원문 PDF와 추출본이 없으므로 이 저장소만으로는 재생성할 수 없다.

### 확인 필요

- 원문 문장이 그대로 들어 있는 RAG 데이터(청크, 구조화표, D8 표 복원행, 기기-위험요인 링크·인덱스)는 넣지 않았다.
  - 이유: 원문 PDF에 공공누리 표시가 없어 재배포 조건을 확인하지 못했다(2026-11-17). 이 저장소는 공개 저장소다. 일부 사례 자료는 공공기관이 아닌 기관의 문서다.
  - 팀원은 팀 드라이브의 로컬 사본을 이 폴더에 두고 쓴다. 발행 기관에서 공공누리 유형을 확인하면 다시 추가한다.
- 정답셋은 AI 보조로 만든 자료이며 전문가 검수 전이다. 독립 현장 검증 결과가 아니다.
- 팀 결정(2026-11-17): AI 출력 형식은 HITL 계약을 따른다. 위험도 계산은 백엔드 정책 `CATALOG-MVP-1.0`(`backend/domain/risk_policy.py`, `contracts/catalog_risk`, #10)을 따른다. 이를 반영한 계약이 v2.1이다(계약 문서 9절). 파이프라인 코드는 아직 v2를 쓴다.
- v2의 3×3 위험도 예시는 안내서 예시를 옮긴 것이며 계산 기준으로 쓰지 않는다.
