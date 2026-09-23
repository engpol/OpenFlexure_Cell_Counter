"""
Benchmark + calibration for the cell counter.

Answers two questions with measurements instead of guesses:

  1. How long does segmentation actually take on this machine?
     (i.e. is a GPU worth requisitioning?)
  2. What is the correct `diameter` for your images?
     This matters twice over: it is the main driver of accuracy AND the
     main driver of runtime. CellPose internally rescales every image so
     that `diameter` becomes 30 px, so the real compute cost is
     approximately  width * height * (30 / diameter)^2  pixels.
     Setting diameter too small silently makes the job much slower.

Usage:
    python benchmark.py path/to/chosen_image.tiff
    python benchmark.py path/to/chosen_image.tiff --sweep 20 25 30 40 50
    python benchmark.py path/to/chosen_image.tiff --repeats 3
"""

import argparse
import os
import statistics
import time

import numpy as np
from PIL import Image


def human(seconds):
    return "%6.2f s" % seconds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image", help="Path to a representative tiled image")
    ap.add_argument("--model", default="cyto2")
    ap.add_argument("--gpu", action="store_true", help="Force GPU")
    ap.add_argument(
        "--sweep",
        nargs="*",
        type=float,
        default=[20, 25, 30, 40, 50],
        help="Diameters to time",
    )
    ap.add_argument("--repeats", type=int, default=1, help="Timed runs per diameter")
    ap.add_argument(
        "--no-estimate",
        action="store_true",
        help="Skip the automatic diameter estimate (which loads a second model)",
    )
    args = ap.parse_args()

    import torch
    from cellpose import models

    gpu = args.gpu or torch.cuda.is_available()
    print("=" * 68)
    print("Device            : %s" % ("GPU" if gpu else "CPU"))
    if gpu:
        print("GPU               : %s" % torch.cuda.get_device_name(0))
    else:
        n = os.cpu_count() or 1
        torch.set_num_threads(n)
        print("CPU threads       : %d" % n)
    print("torch             : %s" % torch.__version__)
    try:
        import cellpose

        print("cellpose          : %s" % getattr(cellpose, "version", "unknown"))
    except Exception:
        pass

    img = np.asarray(Image.open(args.image))
    h, w = img.shape[:2]
    mp = w * h / 1e6
    print("Image             : %d x %d  (%.2f MP)" % (w, h, mp))
    print("=" * 68)

    t0 = time.time()
    model = models.CellposeModel(gpu=gpu, model_type=args.model)
    print("\nModel load        : %s   <-- paid ONCE by the warm worker," % human(time.time() - t0))
    print("                              paid EVERY run by a cold script.")

    # ---- automatic diameter estimate -------------------------------------
    if not args.no_estimate:
        try:
            print("\nEstimating cell diameter (loads the size model)...")
            sizer = models.Cellpose(gpu=gpu, model_type=args.model)
            t0 = time.time()
            out = sizer.eval(img, channels=[0, 0], diameter=None)
            est = out[3]
            est = float(np.mean(est)) if np.ndim(est) else float(est)
            n_est = int((np.unique(out[0]) > 0).sum())
            print("  estimated diameter : %.1f px   (%d cells, %s)"
                  % (est, n_est, human(time.time() - t0)))
            print("  -> if this differs a lot from your configured 25, fix it:")
            print("     it changes both the count and the runtime.")
            del sizer
        except Exception as exc:
            print("  estimate unavailable: %s" % exc)

    # ---- warm-up ---------------------------------------------------------
    print("\nWarm-up run (excluded from timings)...")
    model.eval(img, channels=[0, 0], diameter=args.sweep[0])

    # ---- sweep -----------------------------------------------------------
    print("\n%-10s %-10s %-12s %-14s" % ("diameter", "cells", "median time", "effective MP"))
    print("-" * 68)
    for d in args.sweep:
        times = []
        count = 0
        for _ in range(max(1, args.repeats)):
            t0 = time.time()
            out = model.eval(img, channels=[0, 0], diameter=d)
            times.append(time.time() - t0)
            count = int((np.unique(out[0]) > 0).sum())
        eff_mp = mp * (30.0 / d) ** 2
        print("%-10.1f %-10d %-12s %-14.2f"
              % (d, count, human(statistics.median(times)).strip(), eff_mp))

    print("-" * 68)
    print("""
Reading the table
  * 'effective MP' is what CellPose really processes after rescaling.
    Runtime should track it almost linearly.
  * Pick the diameter that matches your cells, then read off the runtime.
  * If that runtime is a few seconds, a GPU will save you a few seconds --
    probably not worth the hardware request on its own.
  * If it is 30 s or more, a GPU is typically a 10-20x win and worth asking for.
""")


if __name__ == "__main__":
    main()
