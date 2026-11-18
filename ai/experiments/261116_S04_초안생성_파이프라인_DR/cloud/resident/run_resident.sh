#!/bin/bash
# 1) e35-vllm-py311에 faster-whisper 설치(핵심 패키지 변경 시 중단) 2) 평시 상주 그래프 실행·VRAM 측정
set -x
D=/home/elicer/safet/experiments/261116_s04_pipeline_DR; W=$D/resident; cd $W
UV=/home/elicer/venvs/det-yolo/bin/uv; PY=/home/elicer/venvs/e35-vllm-py311/bin/python
$UV pip freeze --python $PY > freeze_before.txt
$UV pip install --dry-run --python $PY faster-whisper==1.2.1 > dryrun.txt 2>&1; cat dryrun.txt
if grep -E "^ [-~] (torch|torchvision|torchaudio|numpy|transformers|vllm|tokenizers|huggingface-hub|xgrammar|pydantic|protobuf|triton|langgraph)==" dryrun.txt; then echo BLOCKED_CORE_CHANGE; exit 2; fi
$UV pip install --python $PY faster-whisper==1.2.1 || exit 3
$UV pip freeze --python $PY > freeze_after.txt; diff freeze_before.txt freeze_after.txt > freeze_diff.txt
$PY -c "import vllm, faster_whisper, ctranslate2; print(chr(79)+chr(75), vllm.__version__, faster_whisper.__version__, ctranslate2.__version__)" || exit 4
X=$W/app_root; mkdir -p $X && tar -xf $D/resident_bundle_v1.tar -C $X
NV=$($PY -c "import nvidia,os;b=os.path.dirname(nvidia.__path__[0]+'/x');print(':'.join(os.path.join(b,d,'lib') for d in os.listdir(b) if os.path.isdir(os.path.join(b,d,'lib'))))")
export LD_LIBRARY_PATH=$NV:$LD_LIBRARY_PATH
mem() { nvidia-smi | grep -oE "[0-9]+MiB / +9728MiB" | head -1 | grep -oE "^[0-9]+"; }
for i in $(seq 1 2400); do m=$(mem); [ "${m:-99999}" -lt 100 ] && break; sleep 1; done; echo gpu_before $(mem)
: > vram.csv; ( while true; do echo "$(date +%s.%N),$(mem)" >> vram.csv; sleep 0.5; done ) & POLL=$!
timeout 1200 $PY $W/run_graph_resident.py $X/hitl_graph_DR/app $W/resident_result.json > graph_log.txt 2>&1; echo "graph exit $?" >> graph_log.txt
for i in $(seq 1 120); do m=$(mem); [ "${m:-99999}" -lt 100 ] && break; sleep 0.5; done; kill $POLL
echo gpu_after $(mem); date; echo RESIDENT_DONE
