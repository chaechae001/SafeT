#!/bin/bash
# Python 3.11 검증(순차): [GPU 비움 대기] → EXAONE 3.5 enum(3.11) → SAM 3 탐지(det-sam3, 3.12) → JSON → LangGraph(3.11, vLLM).
# 두 모델을 동시에 올리지 않는다. 기존 venv·파일은 수정하지 않는다(읽기·실행만).
set -x
D=/home/elicer/safet/experiments/261116_s04_pipeline_DR
P=/home/elicer/venvs/e35-vllm-py311/bin
W=$D/py311_check; mkdir -p $W; cd $D
mem() { nvidia-smi | grep -oE "[0-9]+MiB / +9728MiB" | head -1 | grep -oE "^[0-9]+"; }
ev() { echo "{\"t\": $(date +%s.%N), \"event\": \"$1\", \"mem_mib\": $(mem)}" >> $W/timeline.jsonl; }
waitfree() { for i in $(seq 1 2400); do m=$(mem); [ "${m:-99999}" -lt 100 ] && { ev "$1"; return 0; }; sleep 1; done; ev "$1_timeout"; echo GPU_BUSY_TIMEOUT; exit 5; }
( while true; do echo "$(date +%s.%N),$(mem)" >> $W/vram.csv; sleep 0.5; done ) & POLL=$!
ev start; waitfree gpu_free_0
# 1) EXAONE enum 재현(입력·스크립트는 3.10 실행과 같은 파일)
$P/python infer_exaone35_awq_enum.py prompts_e35_v1.json $W/cloud_outputs_e35_enum_py311.json $W/timeline.jsonl > $W/infer_log_e35_enum_py311.txt 2>&1; echo "e35enum exit $?" >> $W/infer_log_e35_enum_py311.txt
ev e35_exit; waitfree gpu_free_1
# 2) SAM 3 탐지(3.12). 입력은 기존 탐지 입력 폴더의 앞 3장(심볼릭 링크, 원본 수정 없음)
I=/home/elicer/safet/experiments/261116_detect_compare_DR/inputs
mkdir -p $W/sam3_in/images; cp $I/class_map.json $W/sam3_in/; for f in $(ls $I/images | grep jpg | head -3); do ln -sf $I/images/$f $W/sam3_in/images/$f; done
/home/elicer/venvs/det-sam3/bin/python /home/elicer/safet/experiments/261116_detect_compare_DR/detect_compare_v2.py --model sam3 --inputs $W/sam3_in --out $W/sam3_detections.json > $W/sam3_log.txt 2>&1; echo "sam3 exit $?" >> $W/sam3_log.txt
ev sam3_exit; waitfree gpu_free_2
# 3) 3.11 본체: SAM 3 JSON → LangGraph(EXAONE 3.5 AWQ, vLLM)
A=/home/elicer/safet/experiments/261117_hitl_graph_DR/hitl_graph_DR/app
$P/python $D/run_graph_detfile.py $A runs/hitl_graph/bundle_v1.json $W/sam3_detections.json $W/graph_detfile_py311.json > $W/graph_log_py311.txt 2>&1; echo "graph exit $?" >> $W/graph_log_py311.txt
ev graph_exit; waitfree gpu_free_3
kill $POLL; ev end; echo VERIFY_DONE >> $W/graph_log_py311.txt
