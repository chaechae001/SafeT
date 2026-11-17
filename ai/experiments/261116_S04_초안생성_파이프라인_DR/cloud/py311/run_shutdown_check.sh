#!/bin/bash
# 갱신 hitl_graph.py(close 포함) + run_graph_detfile.py로 3.11 그래프를 다시 실행하고, 프로세스 종료 후 GPU 메모리 반환을 확인한다.
set -x
D=/home/elicer/safet/experiments/261116_s04_pipeline_DR; W=$D/py311_check; P=/home/elicer/venvs/e35-vllm-py311/bin
X=/home/elicer/safet/experiments/261117_hitl_graph_py311_DR; mkdir -p $X && tar -xf $D/hitl_graph_bundle_py311_v2.tar -C $X
mem() { nvidia-smi | grep -oE "[0-9]+MiB / +9728MiB" | head -1 | grep -oE "^[0-9]+"; }
ev() { echo "{\"t\": $(date +%s.%N), \"event\": \"$1\", \"mem_mib\": $(mem)}" >> $W/shutdown_timeline.jsonl; }
: > $W/shutdown_timeline.jsonl
for i in $(seq 1 2400); do m=$(mem); [ "${m:-99999}" -lt 100 ] && break; sleep 1; done; ev gpu_free_before
timeout 900 $P/python $X/run_graph_detfile.py $X/hitl_graph_DR/app runs/hitl_graph/bundle_v1.json $W/sam3_detections.json $W/graph_detfile_py311_v2.json > $W/graph_log_py311_v2.txt 2>&1; echo "graph exit $?" >> $W/graph_log_py311_v2.txt
ev proc_exit
for i in $(seq 1 120); do m=$(mem); [ "${m:-99999}" -lt 100 ] && break; sleep 0.5; done; ev gpu_after
ps -eo pid,cmd | grep -E "EngineCore|run_graph_detfile" | grep -v grep >> $W/graph_log_py311_v2.txt; echo SHUTDOWN_CHECK_DONE >> $W/graph_log_py311_v2.txt
