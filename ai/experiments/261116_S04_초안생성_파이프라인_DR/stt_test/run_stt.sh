#!/bin/bash
# faster-whisper를 SAM 3 환경(det-sam3, 3.12)에 추가하고 한국어 인식을 시험한다. 핵심 패키지가 바뀌면 설치하지 않고 멈춘다.
set -x
D=/home/elicer/safet/experiments/261116_s04_pipeline_DR; W=$D/stt_test; cd $W
UV=/home/elicer/venvs/det-yolo/bin/uv; PY=/home/elicer/venvs/det-sam3/bin/python
date
$UV pip freeze --python $PY > freeze_det-sam3_before.txt
$UV pip install --dry-run --python $PY faster-whisper==1.2.1 > dryrun.txt 2>&1; cat dryrun.txt
if grep -E "^ [-~+] (torch|torchvision|numpy|huggingface-hub|timm|sam3|pillow)==" dryrun.txt | grep -E "^ [-~]"; then echo BLOCKED_CORE_CHANGE; exit 2; fi
$UV pip install --python $PY faster-whisper==1.2.1 || exit 3
$UV pip freeze --python $PY > freeze_det-sam3_after.txt
diff freeze_det-sam3_before.txt freeze_det-sam3_after.txt > freeze_diff.txt
$PY -c "import sam3, torch; print(chr(83)+chr(65)+chr(77)+chr(51)+chr(95)+chr(79)+chr(75), torch.__version__)" || exit 4
$PY -c "from huggingface_hub import snapshot_download as s; print(s(chr(100)+chr(101)+chr(101)+chr(112)+chr(100)+chr(109)+chr(108)+chr(47)+chr(102)+chr(97)+chr(115)+chr(116)+chr(101)+chr(114)+chr(45)+chr(119)+chr(104)+chr(105)+chr(115)+chr(112)+chr(101)+chr(114)+chr(45)+chr(108)+chr(97)+chr(114)+chr(103)+chr(101)+chr(45)+chr(118)+chr(51)+chr(45)+chr(116)+chr(117)+chr(114)+chr(98)+chr(111)+chr(45)+chr(99)+chr(116)+chr(50), revision=chr(52)+chr(100)+chr(102)+chr(57)+chr(48)+chr(102)+chr(55)+chr(53)+chr(51)+chr(50)+chr(49)+chr(49)+chr(52)+chr(56)+chr(99)+chr(51)+chr(97)+chr(50)+chr(57)+chr(97)+chr(57)+chr(101)+chr(50)+chr(51)+chr(53)+chr(49)+chr(98)+chr(55)+chr(100)+chr(100)+chr(102)+chr(56)+chr(102)+chr(53)+chr(98)+chr(49)+chr(49)+chr(53)+chr(97)+chr(56)))" > model_path.txt || exit 5
M=$(tail -1 model_path.txt)
NV=$($PY -c "import nvidia,os;b=os.path.dirname(nvidia.__path__[0]+'/x');print(':'.join(os.path.join(b,d,'lib') for d in os.listdir(b) if os.path.isdir(os.path.join(b,d,'lib'))))")
export LD_LIBRARY_PATH=$NV:$LD_LIBRARY_PATH
mem() { nvidia-smi | grep -oE "[0-9]+MiB / +9728MiB" | head -1 | grep -oE "^[0-9]+"; }
for i in $(seq 1 1800); do m=$(mem); [ "${m:-99999}" -lt 100 ] && break; sleep 1; done; echo gpu_before $(mem)
( while true; do echo "$(date +%s.%N),$(mem)" >> vram.csv; sleep 0.5; done ) & POLL=$!
$PY stt_test.py $M audio out_cuda_int8f16.json cuda int8_float16 > log_cuda.txt 2>&1; echo "cuda exit $?" >> log_cuda.txt
kill $POLL
$PY stt_test.py $M audio out_cpu_int8.json cpu int8 > log_cpu.txt 2>&1; echo "cpu exit $?" >> log_cpu.txt
echo gpu_after $(mem); date; echo STT_DONE
