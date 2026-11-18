#!/bin/bash
# 평시 구성 시험: STT(det-sam3) 상주 + EXAONE 3.5(e35-vllm-py311, gpu_memory_utilization=U)를 같은 GPU에 함께 올린다. U=0.70 실패 시 0.75 (0.65는 KV 부족으로 실패, 2026-11-17).
set -x
D=/home/elicer/safet/experiments/261116_s04_pipeline_DR; W=$D/cohost_test; cd $W
SP=/home/elicer/venvs/det-sam3/bin/python; LP=/home/elicer/venvs/e35-vllm-py311/bin/python
M=$(tail -1 $D/stt_test/model_path.txt)
NV=$($SP -c "import nvidia,os;b=os.path.dirname(nvidia.__path__[0]+'/x');print(':'.join(os.path.join(b,d,'lib') for d in os.listdir(b) if os.path.isdir(os.path.join(b,d,'lib'))))")
mem() { nvidia-smi | grep -oE "[0-9]+MiB / +9728MiB" | head -1 | grep -oE "^[0-9]+"; }
ev() { echo "{\"t\": $(date +%s.%N), \"event\": \"$1\", \"mem_mib\": $(mem)}" >> timeline.jsonl; }
: >> timeline.jsonl
for i in $(seq 1 2400); do m=$(mem); [ "${m:-99999}" -lt 100 ] && break; sleep 1; done; ev gpu_free
( while true; do echo "$(date +%s.%N),$(mem)" >> vram.csv; sleep 0.5; done ) & POLL=$!
for U in 0.70; do
  rm -f stt_ready go2 stt_done2 stop
  LD_LIBRARY_PATH=$NV:$LD_LIBRARY_PATH $SP stt_hold.py $M $D/stt_test/audio $W > stt_log_$U.txt 2>&1 & SPID=$!
  for i in $(seq 1 300); do [ -f stt_ready ] && break; sleep 1; done; ev "stt_ready_$U"
  timeout 900 $LP e35_cohost.py $D $D/prompts_e35_v1.json $W $U > e35_log_$U.txt 2>&1; RC=$?; echo "e35 exit $RC" >> e35_log_$U.txt; ev "e35_exit_$U"
  touch stop; wait $SPID; ev "stt_exit_$U"
  for i in $(seq 1 120); do m=$(mem); [ "${m:-99999}" -lt 100 ] && break; sleep 0.5; done; ev "gpu_after_$U"
  [ $RC -eq 0 ] && break
done
kill $POLL; ev end; echo COHOST_DONE
