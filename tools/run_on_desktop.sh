#!/bin/sh
# Launch the OCR preview window on the board's own desktop session.
#
# Useful when driving the board over adb/ssh: the GUI session belongs to the
# desktop user, so the DISPLAY / XAUTHORITY / XDG_RUNTIME_DIR variables of that
# session must be injected explicitly - otherwise cv2.imshow fails.
#
# Usage (as the desktop user, from a shell on the board):
#   sh tools/run_on_desktop.sh [camera_index] [seconds]
#   sh tools/run_on_desktop.sh 2 300
#
# Defaults to camera 2 (USB UVC devices often do not land on /dev/video0) and
# exits after 5 minutes; the script prints recognised text to this terminal.
set -eu

CAM="${1:-2}"
SECS="${2:-300}"
UID_NUM="$(id -u)"
RUNTIME="/run/user/$UID_NUM"

export XDG_RUNTIME_DIR="$RUNTIME"
# Find the Xwayland / X11 auth cookie for the running desktop session.
for candidate in "$RUNTIME"/.mutter-Xwaylandauth.* "$HOME"/.Xauthority; do
    [ -f "$candidate" ] && export XAUTHORITY="$candidate" && break
done
if [ -z "${DISPLAY:-}" ]; then
    for d in :0 :1; do
        [ -e "/tmp/.X11-unix/X${d#:}" ] && export DISPLAY="$d" && break
    done
fi
export DISPLAY="${DISPLAY:-:0}"

echo "DISPLAY=$DISPLAY XAUTHORITY=${XAUTHORITY:-<none>} XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR"
cd "$(dirname "$0")/.."
exec python3 ocr_cpu_test.py --cam "$CAM" --window --auto-secs "$SECS" --interval 8
