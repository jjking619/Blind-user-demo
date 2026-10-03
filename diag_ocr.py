#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OCR pipeline diagnostic: separates "model/decoder broken" from "nothing to read".

Part A renders a synthetic image with known text via cv2.putText and runs OCR on it.
Part B runs OCR on a real captured frame (optional argv[1]) and reports raw detections.

Usage:
  python3 diag_ocr.py                  # synthetic-only check
  python3 diag_ocr.py shot.jpg         # synthetic check + real-frame dump
"""

import os
import sys

import cv2
import numpy as np
from paddleocr import PaddleOCR

SYNTH_PATH = os.path.join(os.environ.get("OCR_OUT", os.path.expanduser("~/ocr_out")), "_synth.jpg")


def dump(tag, result):
    if result is None:
        print("[%s] returned None" % tag)
        return
    page = result[0] if isinstance(result, (list, tuple)) and len(result) else result
    if isinstance(page, dict):  # PaddleOCR 3.x
        print("[%s] dict payload, keys=%s" % (tag, list(page.keys())[:8]))
        print("[%s] rec_texts=%s rec_scores=%s" % (tag, page.get("rec_texts"), page.get("rec_scores")))
        return
    print("[%s] boxes: %s" % (tag, len(page) if page else 0))
    for item in (page or [])[:12]:
        print("   ", item[1] if len(item) > 1 else item)


def main():
    img_path = sys.argv[1] if len(sys.argv) > 1 else None
    ocr = PaddleOCR(use_angle_cls=True, lang="ch", use_gpu=False, show_log=False)

    # Part A: known-good input. If this fails, the problem is in the model/decoder,
    # not in the camera feed.
    synth = np.full((200, 900, 3), 255, np.uint8)
    cv2.putText(synth, "HELLO OCR TEST 12345", (20, 130), cv2.FONT_HERSHEY_SIMPLEX, 2.4, (0, 0, 0), 5)
    try:
        os.makedirs(os.path.dirname(SYNTH_PATH), exist_ok=True)
        cv2.imwrite(SYNTH_PATH, synth)
    except Exception as e:
        print("[synth] write skipped: %s" % str(e)[:120])
    result = ocr.ocr(synth, cls=True)
    print("[synth] frame type: %s, top-level len: %s"
          % (type(result).__name__, len(result) if hasattr(result, "__len__") else "-"))
    dump("synth", result)

    # Part B: real frame. Zero detections here means the camera saw no text.
    if img_path:
        img = cv2.imread(img_path)
        print("[real ] %s shape=%s mean=%.1f"
              % (img_path, img.shape if img is not None else None,
                 float(img.mean()) if img is not None else -1))
        if img is not None:
            dump("real", ocr.ocr(img, cls=True))
    print("[done ]")


if __name__ == "__main__":
    sys.exit(main())
