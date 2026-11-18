#!/bin/bash
# EXAONE 3.5 enum 강제 실행(SAM 3 교체 측정 없음). 시작 전 GPU 100 MiB 미만 확인은 호출 쪽에서 한다.
cd /home/elicer/safet/experiments/261116_s04_pipeline_DR
TL=e35enum_timeline.jsonl; : > $TL; : > e35enum_vram.csv
mem() { nvidia-smi | grep -oE "[0-9]+MiB / +9728MiB" | head -1 | grep -oE "^[0-9]+"; }
( while true; do echo "$(date +%s.%N),$(mem)" >> e35enum_vram.csv; sleep 0.5; done ) & POLL=$!
echo "{\"t\": $(date +%s.%N), \"event\": \"start\", \"mem_mib\": $(mem)}" >> $TL
/home/elicer/venvs/e35-vllm/bin/python infer_exaone35_awq_enum.py prompts_e35_v1.json cloud_outputs_e35_enum_v1.json $TL > infer_log_e35_enum_v1.txt 2>&1; echo "e35enum exit $?" >> infer_log_e35_enum_v1.txt
for i in $(seq 1 240); do m=$(mem); [ "${m:-99999}" -lt 100 ] && break; sleep 0.25; done
echo "{\"t\": $(date +%s.%N), \"event\": \"gpu_free\", \"mem_mib\": $(mem)}" >> $TL
kill $POLL; echo SEQ_DONE >> infer_log_e35_enum_v1.txt
