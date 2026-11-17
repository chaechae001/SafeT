#!/bin/bash
# SAM 3 → 내림 → EXAONE 3.5 7.8B AWQ 순차 실행. 두 모델을 동시에 올리지 않는다(앞 프로세스 종료·메모리 반환 확인 후 다음 단계).
cd /home/elicer/safet/experiments/261116_s04_pipeline_DR
TL=e35_timeline.jsonl; : > $TL; : > e35_vram.csv
mem() { nvidia-smi | grep -oE "[0-9]+MiB / +9728MiB" | head -1 | grep -oE "^[0-9]+"; }
ev() { echo "{\"t\": $(date +%s.%N), \"event\": \"$1\", \"mem_mib\": $(mem)}" >> $TL; }
( while true; do echo "$(date +%s.%N),$(mem)" >> e35_vram.csv; sleep 0.5; done ) & POLL=$!
waitfree() { for i in $(seq 1 240); do m=$(mem); [ "${m:-99999}" -lt 100 ] && break; sleep 0.25; done; ev "$1"; }
ev start
/home/elicer/venvs/det-sam3/bin/python sam3_load_probe.py $TL > sam3_probe_log.txt 2>&1; echo "sam3 exit $?" >> sam3_probe_log.txt
ev sam3_proc_exit; waitfree sam3_gpu_free
/home/elicer/venvs/e35-vllm/bin/python infer_exaone35_awq.py prompts_e35_v1.json cloud_outputs_e35_v1.json $TL > infer_log_e35_v1.txt 2>&1; echo "e35 exit $?" >> infer_log_e35_v1.txt
ev e35_proc_exit; waitfree e35_gpu_free
kill $POLL; ev end; echo SEQ_DONE >> infer_log_e35_v1.txt
