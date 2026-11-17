#!/bin/bash
# v2: 설치 없이 시험만 다시 실행(stt_test.py 수정본).
set -x
W=/home/elicer/safet/experiments/261116_s04_pipeline_DR/stt_test; cd $W
PY=/home/elicer/venvs/det-sam3/bin/python; M=$(tail -1 model_path.txt)
NV=$($PY -c "import nvidia,os;b=os.path.dirname(nvidia.__path__[0]+'/x');print(':'.join(os.path.join(b,d,'lib') for d in os.listdir(b) if os.path.isdir(os.path.join(b,d,'lib'))))")
export LD_LIBRARY_PATH=$NV:$LD_LIBRARY_PATH
mem() { nvidia-smi | grep -oE "[0-9]+MiB / +9728MiB" | head -1 | grep -oE "^[0-9]+"; }
for i in $(seq 1 1800); do m=$(mem); [ "${m:-99999}" -lt 100 ] && break; sleep 1; done; echo gpu_before $(mem)
: > vram.csv; ( while true; do echo "$(date +%s.%N),$(mem)" >> vram.csv; sleep 0.5; done ) & POLL=$!
$PY stt_test.py $M audio out_cuda_int8f16.json cuda int8_float16 > log_cuda.txt 2>&1; echo "cuda exit $?" >> log_cuda.txt
kill $POLL
$PY stt_test.py $M audio out_cpu_int8.json cpu int8 > log_cpu.txt 2>&1; echo "cpu exit $?" >> log_cpu.txt
echo gpu_after $(mem); date; echo STT_DONE
