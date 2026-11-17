#!/bin/bash
# SAM 3 패키지 import에 필요한 누락 모듈을 반복 설치한다(det-sam3 venv에만).
cd ~/safet/experiments/261116_detect_compare_DR
UV=~/venvs/det-yolo/bin/uv
PY=~/venvs/det-sam3/bin/python
export VIRTUAL_ENV=~/venvs/det-sam3
for i in $(seq 1 10); do
  M=$($PY -c "import sam3.model_builder, sam3.model.sam3_image_processor" 2>&1 | sed -n "s/.*No module named '\([^'.]*\).*/\1/p" | head -1)
  [ -z "$M" ] && break
  case "$M" in
    cv2) P=opencv-python-headless ;;
    PIL) P=pillow ;;
    yaml) P=pyyaml ;;
    sklearn) P=scikit-learn ;;
    *) P=$M ;;
  esac
  echo "MISSING $M -> install $P"
  $UV pip install -q "$P"
done
$PY -c "import sam3.model_builder, sam3.model.sam3_image_processor; print('SAM3_IMPORT_OK')" 2>&1 | tail -3
$UV pip freeze > pip_freeze_det-sam3.txt
sha256sum detect_compare.py
echo DEPS_END
