#!/bin/bash
# v2: 설치 없음(v1에서 완료). vLLM spawn 수정 그래프로 평시 상주 실행·VRAM 측정
set -x
D=/home/elicer/safet/experiments/261116_s04_pipeline_DR; W=$D/resident; cd $W
UV=/home/elicer/venvs/det-yolo/bin/uv; PY=/home/elicer/venvs/e35-vllm-py311/bin/python
$PY -c "import vllm, faster_whisper, ctranslate2; print(chr(79)+chr(75), vllm.__version__, faster_whisper.__version__, ctranslate2.__version__)" || exit 4
X=$W/app_root_v2; mkdir -p $X && tar -xf $D/resident_bundle_v2.tar -C $X
NV=$($PY -c "import nvidia,os;b=os.path.dirname(nvidia.__path__[0]+'/x');print(':'.join(os.path.join(b,d,'lib') for d in os.listdir(b) if os.path.isdir(os.path.join(b,d,'lib'))))")
export LD_LIBRARY_PATH=$NV:$LD_LIBRARY_PATH
mem() { nvidia-smi | grep -oE "[0-9]+MiB / +9728MiB" | head -1 | grep -oE "^[0-9]+"; }
for i in $(seq 1 2400); do m=$(mem); [ "${m:-99999}" -lt 100 ] && break; sleep 1; done; echo gpu_before $(mem)
: > vram_v2.csv; ( while true; do echo "$(date +%s.%N),$(mem)" >> vram_v2.csv; sleep 0.5; done ) & POLL=$!
timeout 1200 $PY $W/run_graph_resident.py $X/hitl_graph_DR/app $W/resident_result_v2.json > graph_log_v2.txt 2>&1; echo "graph exit $?" >> graph_log_v2.txt
for i in $(seq 1 120); do m=$(mem); [ "${m:-99999}" -lt 100 ] && break; sleep 0.5; done; kill $POLL
echo gpu_after $(mem); date; echo RESIDENT2_DONE
