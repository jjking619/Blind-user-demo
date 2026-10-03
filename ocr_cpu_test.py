#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI light-adaptive braille converter - CPU path (PaddleOCR) verification script.

Pipeline: USB camera -> light-adaptive preprocessing -> PaddleOCR (CPU) -> text -> [hook] braille

Usage (on the board):
  python3 ocr_cpu_test.py                      # live preview: s = recognize once / a = repeat / q = quit
  python3 ocr_cpu_test.py --list-cams          # probe which /dev/videoN works (not always video0)
  python3 ocr_cpu_test.py --image book.jpg     # recognize a single still image
  python3 ocr_cpu_test.py --cam 2 --no-window  # headless: save artifacts and print only
  python3 ocr_cpu_test.py --no-adaptive        # disable light adaptation (control run)
  python3 ocr_cpu_test.py --braille            # also feed the result to the braille encoder hook

Artifacts per recognition, written to $OCR_OUT (default $HOME/ocr_out):
  shot_<ts>.jpg / marked_<ts>.jpg / result_<ts>.txt
"""

import argparse
import os
import sys
import time

VERSION = "0.3"

RUN_BRAILLE = False  # set from --braille; the encoder itself is not implemented yet

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

OUT_DIR = os.environ.get("OCR_OUT", os.path.join(os.path.expanduser("~"), "ocr_out"))

CFG = {
    "width": 1280,           # must be one of the modes the camera advertises (see --list-cams)
    "height": 720,
    "light_adaptive": True,
    "clahe_clip": 2.5,
    "clahe_grid": 8,
    "dark_mean": 70.0,       # frames dimmer than this get an extra gamma lift
    "auto_interval": 3.0,
    "min_score": 0.55,       # detections below this confidence are dropped
}


def log(*parts):
    print(*parts, flush=True)


def light_adaptive(frame):
    """Return (processed_frame, note). LAB-CLAHE plus gamma lift for dim frames."""
    import cv2
    import numpy as np

    mean_before = float(frame.mean())
    light_note = "mean=%.1f" % mean_before
    if not CFG["light_adaptive"]:
        return frame, light_note + " (adaptive=off)"

    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=CFG["clahe_clip"],
                            tileGridSize=(CFG["clahe_grid"], CFG["clahe_grid"]))
    l = clahe.apply(l)
    out = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)

    if mean_before < CFG["dark_mean"]:
        # Gamma < 1.0 brightens; floor it so near-black frames are not blown out.
        gamma = max(0.5, mean_before / CFG["dark_mean"])
        lut = np.array([((i / 255.0) ** gamma) * 255 for i in range(256)], dtype=np.uint8)
        out = cv2.LUT(out, lut)
        light_note += " -> gamma=%.2f" % gamma

    light_note += " -> mean=%.1f (adaptive=on)" % float(out.mean())
    return out, light_note


def build_ocr(lang="ch"):
    """Instantiate PaddleOCR across 2.x/3.x constructor differences."""
    from paddleocr import PaddleOCR
    errs = []
    for kw in (
        {"use_angle_cls": True, "lang": lang, "use_gpu": False, "show_log": False},
        {"use_angle_cls": True, "lang": lang, "use_gpu": False},
        {"use_textline_orientation": True, "lang": lang, "device": "cpu"},
        {"lang": lang},
    ):
        try:
            ocr = PaddleOCR(**kw)
            log("[ocr] PaddleOCR 初始化成功, 参数: %s" % kw)
            return ocr
        except TypeError as e:
            errs.append("%s -> %s" % (kw, e))
    raise RuntimeError("PaddleOCR 初始化失败, 试过的参数: %s" % " | ".join(errs))


def norm_result(res):
    """Normalize 2.x/3.x outputs into [(text, score, box), ...]."""
    out = []
    if res is None:
        return out
    first = res[0] if isinstance(res, (list, tuple)) and len(res) else res

    d = first if isinstance(first, dict) else None
    if d is not None:  # PaddleOCR 3.x returns a dict payload
        texts = d.get("rec_texts") or []
        scores = d.get("rec_scores") or [1.0] * len(texts)
        polys = d.get("dt_polys") or d.get("rec_polys") or [None] * len(texts)
        for t, s, p in zip(texts, scores, polys):
            if p is not None:
                try:
                    import numpy as np
                    p = np.array(p).reshape(-1, 2)
                except Exception:
                    p = None
            out.append((str(t), float(s), p))
        return out

    for item in (first or []):  # PaddleOCR 2.x returns [box, (text, score)] pairs
        try:
            box, txt, sc = item[0], item[1][0], item[1][1]
            out.append((str(txt), float(sc), box))
        except Exception:
            continue
    return out


def order_readable(items):
    """Sort detections into reading order: top-to-bottom, then left-to-right."""
    def key(it):
        box = it[2]
        try:
            ys = [p[1] for p in box]
            xs = [p[0] for p in box]
            y = sum(ys) / float(len(ys))
            x = min(xs)
            h = max(ys) - min(ys)
            return (round(y / max(h, 1.0)), x)
        except Exception:
            return (0, 0)
    return sorted(items, key=key)


def run_ocr(ocr, frame, cls=True):
    t0 = time.time()
    try:
        res = ocr.ocr(frame, cls=cls)
    except TypeError:
        res = ocr.predict(frame)
    items = order_readable([it for it in norm_result(res) if it[1] >= CFG["min_score"]])
    return items, (time.time() - t0) * 1000.0


def text_to_braille(text):
    """Encode Chinese text into GB/T 15720 braille. Not implemented yet."""
    raise NotImplementedError(
        "braille encoding not implemented yet: needs GB/T 15720 "
        "(initial + final + tone + word spacing) mapped onto 6-dot cells"
    )


def open_cam(idx):
    import cv2
    for backend in (cv2.CAP_V4L2, 0):
        cap = cv2.VideoCapture(idx, backend) if backend else cv2.VideoCapture(idx)
        if cap is None or not cap.isOpened():
            if cap is not None:
                cap.release()
            continue
        # UVC defaults to YUYV 640x480; request MJPG first to reach 720p/1080p.
        try:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        except Exception:
            pass
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CFG["width"])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CFG["height"])
        cap.set(cv2.CAP_PROP_FPS, 30)
        ok, frame = cap.read()
        if ok and frame is not None:
            return cap, frame
        cap.release()
    return None, None


def list_cams(max_idx=12):
    import cv2
    hits = []
    for i in range(max_idx):
        cap, frame = open_cam(i)
        if cap is None:
            continue
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        hits.append(i)
        log("  /dev/video%-2d  OK  %dx%d  mean=%.1f" % (i, w, h, float(frame.mean())))
        cap.release()
    if not hits:
        log("  未找到可用摄像头节点 (检查 USB 是否插好 / ls -l /dev/video* / 是否在 video 组)")
    else:
        log("  可用节点: %s (用 --cam N 指定)" % ", ".join(str(i) for i in hits))
    return hits


def recognize(ocr, frame, tag=""):
    import cv2
    proc, light_note = light_adaptive(frame)
    log("[光] %s" % light_note)
    items, ms = run_ocr(ocr, proc)
    text = "".join(t for t, _, _ in items)
    log("[时] OCR 耗时 %.0f ms, 字符 %d" % (ms, len(text)))
    log("[文] %s" % (text if text else "(未识别到文字)"))

    if RUN_BRAILLE and text:
        try:
            log("[盲] %s" % text_to_braille(text))
        except NotImplementedError as e:
            log("[盲] 未实现: %s" % e)

    ts = time.strftime("%Y%m%d_%H%M%S")
    os.makedirs(OUT_DIR, exist_ok=True)
    if frame is not None:
        cv2.imwrite(os.path.join(OUT_DIR, "shot_%s%s.jpg" % (tag, ts)), frame)
    marked = proc.copy()
    try:
        import numpy as np
        for t, sc, box in items:
            pts = np.array(box)
            if pts.ndim == 2 and pts.shape[0] >= 4:
                cv2.polylines(marked, [pts.astype(np.int32)], True, (0, 255, 0), 2)
    except Exception as e:
        log("[warn] 画框失败: %s" % str(e)[:120])
    cv2.imwrite(os.path.join(OUT_DIR, "marked_%s%s.jpg" % (tag, ts)), marked)
    with open(os.path.join(OUT_DIR, "result_%s%s.txt" % (tag, ts)), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    log("[存] %s/marked_%s%s.jpg" % (OUT_DIR, tag, ts))
    return text


def main():
    global RUN_BRAILLE
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", type=int, default=0, help="摄像头节点序号(/dev/videoN)")
    ap.add_argument("--list-cams", action="store_true", help="列出可用摄像头节点后退出")
    ap.add_argument("--image", default=None, help="对单张图片识别后退出")
    ap.add_argument("--no-window", action="store_true", help="不弹窗(无桌面环境)")
    ap.add_argument("--no-adaptive", action="store_true", help="关闭光影自适应预处理")
    ap.add_argument("--interval", type=float, default=CFG["auto_interval"], help="'a' 连续识别间隔(秒)")
    ap.add_argument("--auto-secs", type=float, default=0.0,
                    help="无人值守模式: 每 --interval 秒识别一次, 跑满该秒数后自动退出")
    ap.add_argument("--window", action="store_true",
                    help="强制显示预览窗(配合 --auto-secs: 边显示边定时识别)")
    ap.add_argument("--braille", action="store_true",
                    help="识别后调用盲文编码钩子(当前未实现, 只打印提示)")
    args = ap.parse_args()

    CFG["light_adaptive"] = not args.no_adaptive
    RUN_BRAILLE = args.braille

    import cv2
    import numpy as np
    log("== AI 光影自适应盲文即时转换系统 / 方案一(CPU) v%s ==" % VERSION)
    log("cv2 %s | numpy %s" % (cv2.__version__, np.__version__))

    ocr = build_ocr()

    if args.list_cams:
        list_cams()
        return 0

    if args.image:
        frame = cv2.imread(args.image)
        if frame is None:
            log("读不到图片: %s" % args.image)
            return 1
        recognize(ocr, frame, tag="img_")
        return 0

    cap, frame = open_cam(args.cam)
    if cap is None:
        log("打开 /dev/video%d 失败: 依次排查 1) ls -l /dev/video*  2) 是否在 video 组  3) --list-cams" % args.cam)
        return 1
    log("摄像头 /dev/video%d 打开成功 %dx%d" % (args.cam, frame.shape[1], frame.shape[0]))

    win = "ocr_cam"
    can_show = (not args.no_window) and (args.window or bool(os.environ.get("DISPLAY")))
    auto_until = 0.0
    if args.auto_secs > 0:
        auto_until = time.time() + args.auto_secs
        log("自动模式: 每 %.1fs 识别一次, 共 %.0fs 后退出(预览窗=%s, 结果写入 %s)"
            % (args.interval, args.auto_secs, can_show, OUT_DIR))
    else:
        if not can_show:
            log("无 DISPLAY 或指定了 --no-window: 无窗口模式(按 s 识别并存图, 用 adb pull 取回)")
        log("==== 对准书本: s=识别一次  a=连续识别  q=退出 ====")

    last_key = None
    auto_next = 0.0
    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            log("读取帧失败, 重试...")
            time.sleep(0.2)
            continue

        key = -1
        if can_show:
            try:
                cv2.imshow(win, frame)
                key = cv2.waitKey(1) & 0xFF
            except Exception as e:
                log("imshow 不可用(%s), 转无窗口模式" % str(e)[:120])
                can_show = False

        if key == ord("q"):
            break
        if key == ord("s"):
            recognize(ocr, frame, tag="cam_")
        if key == ord("a"):
            last_key = "a" if last_key != "a" else None
            log("[模式] 连续识别 %s" % ("开(每 %.1fs)" % args.interval if last_key == "a" else "关"))
            auto_next = 0.0

        if auto_until:
            if time.time() >= auto_next:
                recognize(ocr, frame, tag="auto_")
                auto_next = time.time() + args.interval
                if time.time() >= auto_until:
                    break
            time.sleep(0.05)
            continue

        if last_key == "a" and time.time() >= auto_next:
            recognize(ocr, frame, tag="auto_")
            auto_next = time.time() + args.interval

        if not can_show:
            time.sleep(0.05)

    cap.release()
    if can_show:
        cv2.destroyAllWindows()
    log("退出。产物目录: %s" % OUT_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
