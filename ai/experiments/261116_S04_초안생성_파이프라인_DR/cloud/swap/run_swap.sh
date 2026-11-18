#!/bin/bash
# 사진 경로 모델 교체 자동화 시험. 갱신 그래프(매칭 보강) 묶음 사용. 사진 1장(기존 탐지 입력, 심볼릭 링크).
set -x
D=/home/elicer/safet/experiments/261116_s04_pipeline_DR; W=$D/swap; cd $W
PY=/home/elicer/venvs/e35-vllm-py311/bin/python
X=$W/app_root; mkdir -p $X && tar -xf $D/swap_bundle_v1.tar -C $X
I=/home/elicer/safet/experiments/261116_detect_compare_DR/inputs
mkdir -p sam3_in/images; cp $I/class_map.json sam3_in/; f=$(ls $I/images | grep jpg | head -1); ln -sf $I/images/$f sam3_in/images/$f
NV=$($PY -c "import nvidia,os;b=os.path.dirname(nvidia.__path__[0]+'/x');print(':'.join(os.path.join(b,d,'lib') for d in os.listdir(b) if os.path.isdir(os.path.join(b,d,'lib'))))")
export LD_LIBRARY_PATH=$NV:$LD_LIBRARY_PATH
mem() { nvidia-smi | grep -oE "[0-9]+MiB / +9728MiB" | head -1 | grep -oE "^[0-9]+"; }
for i in $(seq 1 2400); do m=$(mem); [ "${m:-99999}" -lt 100 ] && break; sleep 1; done; echo gpu_before $(mem)
: > vram.csv; ( while true; do echo "$(date +%s.%N),$(mem)" >> vram.csv; sleep 0.5; done ) & POLL=$!
timeout 1500 $PY $W/run_photo_swap.py $X/hitl_graph_DR/app $W/sam3_in $W/swap_result.json > swap_log.txt 2>&1; echo "swap exit $?" >> swap_log.txt
for i in $(seq 1 120); do m=$(mem); [ "${m:-99999}" -lt 100 ] && break; sleep 0.5; done; kill $POLL
echo gpu_after $(mem); date; echo SWAP_DONE
