#!/usr/bin/env bash
# S04 프로토타입 전체 재현(오프라인·모의 LLM). 모델 호출 없음. 작업 폴더에서 실행.
set -euo pipefail
export PYTHONIOENCODING=utf-8
UVR="uv run -q --with jsonschema==4.* --with referencing --with rfc3339-validator --with rfc3987 python"
# runs를 지우되 사람 판정 시트 폴더(runs/hitl_recommend/judgement)는 보존한다(사람이 채운 판정이 지워지지 않게).
mkdir -p runs/hitl_recommend
find runs -mindepth 1 -maxdepth 1 ! -name hitl_recommend -exec rm -rf {} +
find runs/hitl_recommend -mindepth 1 -maxdepth 1 ! -name judgement -exec rm -rf {} +
$UVR src/run_s04.py --request inputs/tc01_request.json --out runs/tc01_offline_provisional
$UVR src/run_s04.py --request inputs/tc01_request.json --out runs/tc01_offline_strict --criteria-mode strict
$UVR src/run_s04.py --request inputs/tc01_request.json --out runs/tc01_mock_llm --mode mock_llm --mock-llm inputs/mock/tc01_mock_llm_content.txt
$UVR src/run_cases.py
# Cloud 모델 출력 재생(Cloud 실행 결과 cloud/outputs/cloud_outputs.json 필요, 모델 호출 없음)
$UVR src/run_s04.py --request inputs/tc01_request.json --out runs/tc01_cloud_qwen25vl3b_attempt2 --mode replay --replay cloud/outputs/cloud_outputs.json --attempt 1
$UVR src/eval_cloud_replay.py
# 개선 A·B·AB·B2·AB2 내부 비교(Cloud 출력 v2·v3 재생, 모델 호출 없음)
$UVR src/eval_improvements.py
# 3차: A2·A3 + C1·C2 + 기기 매핑·불일치 필터(Cloud 출력 v4~v7 재생), 매핑표·라벨링 CSV
$UVR src/eval_round3.py
$UVR src/export_equipment_mapping.py
# 사진 분석 전환: v2 계약 스키마, 사진 케이스, 관찰 단계 평가(Cloud 출력 재생), 항목 단계 준비·모의 점검
$UVR contract_v2/build_v2_schemas.py
$UVR src/build_photo_cases.py
PYTHONIOENCODING=utf-8 uv run -q --with pillow python src/build_observe_v3.py
$UVR src/eval_observe.py
$UVR src/photo_pipeline_dryrun.py
$UVR src/check_outputs.py
PYTHONIOENCODING=utf-8 uv run -q --with jsonschema==4.* --with referencing --with rfc3339-validator --with rfc3987 python src/negative_test.py
# Human-in-the-Loop 추천형(2026-11-16): 검색만 3종 + Cloud 출력 재생(LLM 단독·RAG+LLM), 스키마·계약 v2·정답셋 v2 평가, 보고서
$UVR src/hitl_recommend.py replay cloud/outputs/cloud_outputs_hitl_v1.json
$UVR src/check_hitl.py
$UVR src/hitl_contract_v2.py
# EXAONE API(외부) 응답 재생(api/outputs/exaone_hitl_v1.json 필요, API 호출 없음)과 3×3 임시 위험도 규칙(임시 가정, 팀·전문가 확정 전)
$UVR src/hitl_exaone.py replay
# EXAONE 3.5 7.8B AWQ(Elice Cloud, vLLM) 출력 재생(cloud/e35/outputs/cloud_outputs_e35_v1.json 필요, 모델 호출 없음)
$UVR src/hitl_exaone.py replay_e35
# EXAONE 3.5 enum 강제 guided JSON 출력 재생(cloud/e35/outputs/cloud_outputs_e35_enum_v1.json 필요, 모델 호출 없음)
$UVR src/hitl_exaone.py replay_e35_enum
$UVR src/risk_rule.py
$UVR src/eval_hitl.py --goldset
$UVR src/report_hitl.py > /dev/null
# 설명문 판단 표현 필터 시험(파이프라인 미연결, 규칙 v0.2-draft, 팀 확정 전)
$UVR src/rationale_filter.py > /dev/null
# 판정 시트가 없을 때만 새로 만든다(있으면 사람 판정 보존). 집계 자체 시험은 합성값.
[ -f runs/hitl_recommend/judgement/hitl_판정시트_v1.xlsx ] || uv run -q --with openpyxl python src/judge_hitl.py build > /dev/null
uv run -q --with openpyxl python src/judge_hitl.py selftest > /dev/null
# LangGraph 흐름 시연(EXAONE 3.5 AWQ 고정, Cloud enum 응답 재생, 합성 탐지·합성 사람 입력, 계약 v2 5종 검증, 척도 노션 H1+해석 B)
uv run -q --with langgraph --with jsonschema==4.* --with referencing --with rfc3339-validator --with rfc3987 python src/hitl_graph.py demo > /dev/null
# 실제 SAM 3 탐지 응답(평가셋 nene 묶음 7장) → 규칙 R1~R5 → 그래프(LLM 재생, 합성 사람 입력). T=0.50은 비교 평가값(서비스 임계값 아님)
uv run -q --with langgraph --with jsonschema==4.* --with referencing --with rfc3339-validator --with rfc3987 python src/hitl_graph.py demo_sam3 > /dev/null
# 입력 3종(사진·음성·텍스트) 분기 시험(재생 모드, 합성 사람 입력)
uv run -q --with langgraph --with jsonschema==4.* --with referencing --with rfc3339-validator --with rfc3987 python src/test_hitl_inputs.py > /dev/null
echo "ALL PASS"
