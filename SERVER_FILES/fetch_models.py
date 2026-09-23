"""
fetch_models.py -- get CellPose model weights onto a server with no internet.

CellPose downloads its weights from cellpose.org the first time a model is
loaded. On an isolated analysis machine that fails, and because it happens
during startup the worker never begins listening -- which the Raspberry Pi sees
only as "connection refused".

The weights are needed exactly once. Three ways to get them there:

  1. ONLINE SERVER -- just warm the cache in place:
         python fetch_models.py --download

  2. OFFLINE SERVER -- pack on a machine that has internet and CellPose
     installed, then move the archive across on a USB stick:
         python fetch_models.py --pack                  # online machine
         python fetch_models.py --unpack cellpose_models.tar.gz   # server

  3. Manually copy the whole ~/.cellpose/models directory across.

Check what is already present:
         python fetch_models.py --check
"""

from __future__ import print_function

import argparse
import os
import shutil
import sys
import tarfile


def models_dir():
    """Where CellPose keeps its weights, honouring the override we set."""
    override = os.environ.get("CELLPOSE_LOCAL_MODELS_PATH")
    if override:
        return os.path.join(override, "models") if not override.rstrip(
            os.sep).endswith("models") else override
    return os.path.join(os.path.expanduser("~"), ".cellpose", "models")


def list_present(path):
    if not os.path.isdir(path):
        return []
    return sorted(f for f in os.listdir(path)
                  if not f.startswith(".") and
                  os.path.isfile(os.path.join(path, f)))


def cmd_check(args):
    path = models_dir()
    print("Model directory: %s" % path)
    files = list_present(path)
    if not files:
        print("  EMPTY -- CellPose will try to download on first use.")
        return 1
    total = sum(os.path.getsize(os.path.join(path, f)) for f in files)
    for f in files:
        size = os.path.getsize(os.path.join(path, f)) / 1e6
        print("  %-32s %8.1f MB" % (f, size))
    print("  %d file(s), %.0f MB total" % (len(files), total / 1e6))
    return 0


def cmd_download(args):
    """
    Trigger CellPose's own downloader.

    Deliberately uses CellPose's code rather than hardcoded URLs, so this keeps
    working if upstream moves the files.
    """
    try:
        from cellpose import models
    except ImportError:
        print("ERROR: cellpose is not installed in this environment.")
        print("       conda activate cellcount   (then retry)")
        return 2

    print("Downloading weights for model '%s'..." % args.model)
    print("(CellPose writes them to %s)" % models_dir())
    try:
        models.CellposeModel(gpu=False, model_type=args.model)
        print("  segmentation model OK")
    except Exception as exc:
        print("ERROR: %s" % exc)
        print("")
        print("If this is a DNS or connection error, this machine has no")
        print("internet. Use --pack on a connected machine instead.")
        return 1

    if args.size_model:
        try:
            models.Cellpose(gpu=False, model_type=args.model)
            print("  size model OK (needed by benchmark.py --diameter estimation)")
        except Exception as exc:
            print("  WARNING: size model not fetched: %s" % exc)

    return cmd_check(args)


def cmd_pack(args):
    """Download if needed, then archive the model directory."""
    path = models_dir()
    if not list_present(path):
        print("No weights cached yet -- downloading first.")
        rc = cmd_download(args)
        if rc not in (0,):
            return rc

    files = list_present(path)
    if not files:
        print("ERROR: nothing to pack.")
        return 1

    out = args.output
    print("\nPacking %d file(s) into %s" % (len(files), out))
    with tarfile.open(out, "w:gz") as tar:
        for f in files:
            tar.add(os.path.join(path, f), arcname=os.path.join("models", f))
    print("Done: %s (%.0f MB)" % (out, os.path.getsize(out) / 1e6))
    print("")
    print("Copy that file to the server, then run there:")
    print("    python fetch_models.py --unpack %s" % os.path.basename(out))
    return 0


def _safe_extract(tar, dest):
    """Reject archive members that would escape the destination directory."""
    dest_abs = os.path.abspath(dest)
    for member in tar.getmembers():
        target = os.path.abspath(os.path.join(dest, member.name))
        if not target.startswith(dest_abs + os.sep) and target != dest_abs:
            raise RuntimeError("Refusing unsafe path in archive: %s" % member.name)
        if member.issym() or member.islnk():
            raise RuntimeError("Refusing link in archive: %s" % member.name)
    tar.extractall(dest)


def cmd_unpack(args):
    src = args.unpack
    if not os.path.isfile(src):
        print("ERROR: no such file: %s" % src)
        return 1

    path = models_dir()
    parent = os.path.dirname(path.rstrip(os.sep))
    if not os.path.isdir(parent):
        os.makedirs(parent)

    print("Unpacking %s -> %s" % (src, parent))
    with tarfile.open(src, "r:gz") as tar:
        _safe_extract(tar, parent)
    print("Done.")
    return cmd_check(args)


def main():
    ap = argparse.ArgumentParser(
        description="Provision CellPose model weights, online or offline.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true",
                   help="Report which weights are already present")
    g.add_argument("--download", action="store_true",
                   help="Fetch weights into the local cache (needs internet)")
    g.add_argument("--pack", action="store_true",
                   help="Download if needed, then build a portable archive")
    g.add_argument("--unpack", metavar="ARCHIVE",
                   help="Install weights from an archive built with --pack")
    ap.add_argument("--model", default="cyto2",
                    help="Model name (default: cyto2)")
    ap.add_argument("--output", default="cellpose_models.tar.gz",
                    help="Archive filename for --pack")
    ap.add_argument("--no-size-model", dest="size_model", action="store_false",
                    help="Skip the size model used for diameter estimation")
    args = ap.parse_args()

    if args.check:
        return cmd_check(args)
    if args.download:
        return cmd_download(args)
    if args.pack:
        return cmd_pack(args)
    if args.unpack:
        return cmd_unpack(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
