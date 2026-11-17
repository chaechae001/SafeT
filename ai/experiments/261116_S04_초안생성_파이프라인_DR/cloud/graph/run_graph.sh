#!/bin/bash
# LangGraph 흐름을 EXAONE 3.5 AWQ(vLLM)로 Cloud에서 실행. langgraph는 e35-vllm venv에만 설치(사용자 승인 2026-11-17).
# 핵심 패키지(torch·transformers·vllm·pydantic·numpy·xgrammar·huggingface-hub·tokenizers·triton)가 바뀌면 설치하지 않고 멈춘다.
set -x
cd /home/elicer/safet/experiments/261116_s04_pipeline_DR
P=/home/elicer/venvs/e35-vllm/bin
date
$P/pip install --dry-run langgraph==1.2.22 rfc3339-validator rfc3987 > lg_dryrun.txt 2>&1
grep "Would install" lg_dryrun.txt
if grep "Would install" lg_dryrun.txt | grep -qiE " (torch|torchvision|torchaudio|transformers|vllm|pydantic|pydantic-core|pydantic_core|numpy|xgrammar|huggingface-hub|huggingface_hub|tokenizers|triton)-[0-9]"; then echo "BLOCKED core package change"; exit 2; fi
$P/pip install langgraph==1.2.22 rfc3339-validator rfc3987 || exit 3
$P/python -c "import vllm,torch,transformers,langgraph,importlib.metadata as m;print(chr(86)+chr(69)+chr(82)+chr(83),vllm.__version__,torch.__version__,transformers.__version__,m.version(chr(108)+chr(97)+chr(110)+chr(103)+chr(103)+chr(114)+chr(97)+chr(112)+chr(104)))" || exit 4
M=$(nvidia-smi | grep -oE '[0-9]+MiB / +9728MiB' | head -1 | grep -oE '^[0-9]+'); echo gpu_mem_before $M; [ "$M" -lt 100 ] || { echo GPU_BUSY; exit 5; }
W=/home/elicer/safet/experiments/261117_hitl_graph_DR
rm -rf $W/hitl_graph_DR; mkdir -p $W && tar -xf hitl_graph_bundle_v1.tar -C $W
cd $W/hitl_graph_DR/app
timeout 1800 $P/python src/hitl_graph.py demo --backend vllm --bundle runs/hitl_graph/bundle_v1.json --tag _vllm; echo "graph exit $?"
nvidia-smi | grep -oE '[0-9]+MiB / +9728MiB' | head -1
date; echo GRAPH_DONE
