#!/bin/sh
# Install the pinned dependency set on the board from pre-downloaded wheels.
#
# Use this when the board cannot reach a package index reliably: long transfers
# get cut mid-flight (read timeouts / SSL resets), so wheels are fetched on a
# host machine and pushed over, then installed offline here.
#
# Host side (same Python minor version as the board):
#   pip download -d ./wheels --platform manylinux2014_aarch64 \
#     --platform manylinux_2_17_aarch64 --platform manylinux_2_27_aarch64 \
#     --platform manylinux_2_28_aarch64 --python-version 3.10 --implementation cp \
#     --only-binary=:all: -c constraints.txt -r requirements.txt
#   adb push ./wheels /home/<user>/ocr_test/wheels
#
# Board side (run with the SAME interpreter you use to run the program):
#   sh tools/install_deps.sh /home/pi/ocr_test/wheels
#   sh tools/install_deps.sh /home/pi/ocr_test/wheels ~/.pyenv/versions/3.10.15/bin/python3
#
# Why the extra steps below: paddlepaddle 2.6.2 and opencv 4.6 are built against
# NumPy 1.x, and opencv-python / opencv-python-headless / opencv-contrib-python
# share one cv2/ directory - uninstalling one of them after the others are
# installed removes files that cv2 needs.
set -eu

W="${1:-}"
PY="${2:-python3}"
PINS="${3:-numpy==1.26.4 scipy==1.14.1 scikit-image==0.25.2 tifffile==2024.9.20 pandas==2.2.3 opencv-python==4.6.0.66 opencv-contrib-python==4.6.0.66 paddlepaddle==2.6.2 paddleocr==2.7.3 setuptools}"

if [ -z "$W" ] || [ ! -d "$W" ]; then
    echo "usage: sh $0 <wheel_dir> [python_executable] [pinned_packages]"
    exit 2
fi

echo "== target interpreter =="
"$PY" -V
SITE=$("$PY" -c 'import site; print(site.getsitepackages()[0])')

echo "== 1/3 drop every opencv build (they share one cv2/ directory) =="
"$PY" -m pip uninstall -y opencv-python opencv-contrib-python opencv-python-headless 2>&1 | tail -2 || true
rm -rf "$SITE"/cv2 "$SITE"/cv2/*.so "$SITE"/cv2/python-* 2>/dev/null || true

echo "== 2/3 install pinned set from $W =="
"$PY" -m pip install --no-index --find-links "$W" $PINS 2>&1 | tail -3

echo "== 3/3 import check =="
"$PY" - <<'PY'
import importlib
for name in ("numpy", "cv2", "paddle", "paddleocr", "scipy", "skimage", "imgaug"):
    try:
        mod = importlib.import_module(name)
        print("OK   %-11s %s" % (name, getattr(mod, "__version__", "?")))
    except Exception as exc:
        print("FAIL %-11s %s: %s" % (name, type(exc).__name__, str(exc)[:140]))
PY
