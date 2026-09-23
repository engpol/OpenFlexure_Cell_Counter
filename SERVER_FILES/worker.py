"""
CellPose segmentation worker for the OpenFlexure cell counter.

Runs on the analysis server (Windows, Linux or macOS). Loads the CellPose
model ONCE at startup and keeps it resident in memory, so each request pays
only the inference cost -- not the model load cost.

Start with:
    python -m uvicorn worker:app --host 127.0.0.1 --port 8000

Configuration is via environment variables (see CONFIG block below).
"""

import base64
import inspect
import io
import logging
import os
import secrets
import threading
import time
from typing import Optional

import numpy as np
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from PIL import Image

# Pillow >= 9.1 renamed the resampling enums; support both.
try:
    _NEAREST = Image.Resampling.NEAREST
except AttributeError:  # pragma: no cover - older Pillow
    _NEAREST = Image.NEAREST

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
)
log = logging.getLogger("cellpose-worker")

# --------------------------------------------------------------------------
# CONFIG
# --------------------------------------------------------------------------
# Shared secret. The Pi must send it as "Authorization: Bearer <token>".
# Generate one with:  python -c "import secrets; print(secrets.token_urlsafe(32))"
AUTH_TOKEN = os.getenv("CELLCOUNT_TOKEN", "")

# Either a built-in name ("cyto2", "nuclei", ...) or an absolute path to a
# model file trained in the CellPose GUI. Paths are detected automatically.
MODEL_TYPE = os.getenv("CELLCOUNT_MODEL", "cyto2")
USE_GPU = os.getenv("CELLCOUNT_GPU", "auto").lower()  # "auto" | "1" | "0"

# Defaults, overridable per request.
DEFAULT_DIAMETER = float(os.getenv("CELLCOUNT_DIAMETER", "25"))
DEFAULT_FLOW_THRESHOLD = float(os.getenv("CELLCOUNT_FLOW_THRESHOLD", "0.4"))
DEFAULT_CELLPROB_THRESHOLD = float(os.getenv("CELLCOUNT_CELLPROB_THRESHOLD", "0.0"))

# Longest edge of the returned mask PNG. The Pi GUI thumbnails to 300 px,
# so there is no point shipping a full-resolution mask over the network.
DEFAULT_MASK_MAX_DIM = int(os.getenv("CELLCOUNT_MASK_MAX_DIM", "1200"))

# Reject absurdly large uploads (bytes).
MAX_UPLOAD_BYTES = int(os.getenv("CELLCOUNT_MAX_UPLOAD_BYTES", str(64 * 1024 * 1024)))

# If no token is configured, run without authentication rather than inventing one 
# The install_service.sh script sets an auth token, which may differ from Pi.
# If you really need to use auth, then set CELLCOUNT_TOKEN on the Pi to match the server, and change below

#AUTH_REQUIRED = bool(AUTH_TOKEN)
AUTH_REQUIRED = False


if not AUTH_REQUIRED:
    log.warning("=" * 70)
    log.warning("CELLCOUNT_TOKEN is not set -- running WITHOUT authentication.")
    log.warning("To require a token, set CELLCOUNT_TOKEN and restart.")
    log.warning("=" * 70)

# --------------------------------------------------------------------------
# MODEL
# --------------------------------------------------------------------------
_model = None
_model_lock = threading.Lock()  # CellPose models are not thread-safe.
_device = "unknown"


def gpu_diagnostics():
    """
    Work out whether CUDA is usable, and if not, say precisely why.

    The failure mode this exists to catch: installing the CPU-only PyTorch
    wheel on a machine that HAS an NVIDIA GPU. torch.cuda.is_available() then
    returns False, the worker quietly runs on CPU, and everything works -- just
    ten times slower, with nothing to indicate why. Distinguishing "no CUDA in
    this torch build" from "no GPU visible" turns a silent slowdown into a
    one-line fix.
    """
    info = {"available": False, "reason": None, "device_name": None,
            "torch_version": None, "torch_cuda_build": None,
            "vram_gb": None, "advice": None, "compute_capability": None,
            "torch_arch_list": None}
    try:
        import torch
    except ImportError:
        info["reason"] = "torch is not installed"
        info["advice"] = "pip install torch --index-url https://download.pytorch.org/whl/cpu"
        return info

    info["torch_version"] = torch.__version__
    info["torch_cuda_build"] = torch.version.cuda  # None for CPU-only wheels

    if torch.version.cuda is None:
        info["reason"] = "this PyTorch is a CPU-only build (no CUDA support compiled in)"
        info["advice"] = (
            "If this machine has an NVIDIA GPU, reinstall PyTorch from a CUDA "
            "index, e.g.  pip install --force-reinstall torch "
            "--index-url https://download.pytorch.org/whl/cu128")
        return info

    try:
        if not torch.cuda.is_available():
            info["reason"] = ("PyTorch has CUDA support but no usable GPU was "
                              "found (driver missing, too old, or no NVIDIA card)")
            info["advice"] = ("Run 'nvidia-smi'. If it fails, install the NVIDIA "
                              "driver. If it reports a CUDA version LOWER than "
                              "this torch build (%s), install a matching or older "
                              "PyTorch CUDA wheel." % torch.version.cuda)
            return info

        name = torch.cuda.get_device_name(0)
        props = torch.cuda.get_device_properties(0)
        vram = round(props.total_memory / (1024 ** 3), 1)
        major, minor = torch.cuda.get_device_capability(0)
        device_arch = "sm_%d%d" % (major, minor)

        info["device_name"] = name
        info["vram_gb"] = vram
        info["compute_capability"] = "%d.%d" % (major, minor)

        # torch.cuda.is_available() being True is NOT enough. Newer PyTorch
        # CUDA builds ship kernels only for recent architectures, so an older
        # card (e.g. a Pascal GTX 10-series, sm_61) is "available" yet has no
        # usable kernels -- CellPose then fails or silently misbehaves.
        try:
            arch_list = torch.cuda.get_arch_list()
        except Exception:
            arch_list = []
        info["torch_arch_list"] = arch_list

        if arch_list:
            dev_val = major * 10 + minor
            # A cubin for sm_XY runs on sm_XZ when Z >= Y within the same major.
            usable = any(
                a.startswith("sm_") and a[3:].isdigit()
                and int(a[3:]) // 10 == major and int(a[3:]) <= dev_val
                for a in arch_list)
            if not usable:
                info["reason"] = (
                    "GPU %s is compute capability %d.%d (%s), but this PyTorch "
                    "build only has kernels for: %s"
                    % (name, major, minor, device_arch, ", ".join(arch_list)))
                info["advice"] = (
                    "Either install a PyTorch CUDA build that supports %s -- an "
                    "older CUDA index such as cu126 usually does -- or just run "
                    "on CPU, which for this workload costs only a few seconds "
                    "per sample." % device_arch)
                return info

        info["available"] = True
        return info
    except Exception as exc:
        info["reason"] = "CUDA check raised: %s" % exc
        info["advice"] = "Run 'nvidia-smi' to confirm the driver is working."
        return info


_gpu_info = {}


def _resolve_gpu() -> bool:
    """Decide CPU vs GPU, logging the reasoning either way."""
    global _gpu_info
    _gpu_info = gpu_diagnostics()

    if _gpu_info["torch_version"]:
        log.info("PyTorch %s (CUDA build: %s)", _gpu_info["torch_version"],
                 _gpu_info["torch_cuda_build"] or "none - CPU-only wheel")

    forced = USE_GPU in ("1", "true", "yes")
    disabled = USE_GPU in ("0", "false", "no")

    if disabled:
        log.info("GPU disabled by CELLCOUNT_GPU=%s. Using CPU.", USE_GPU)
        return False

    if _gpu_info["available"]:
        log.info("GPU detected: %s (%.1f GB VRAM). Using GPU.",
                 _gpu_info["device_name"], _gpu_info["vram_gb"])
        return True

    # No GPU. Say why, and how to fix it if it looks like a mistake.
    if forced:
        log.warning("CELLCOUNT_GPU=%s requested a GPU, but: %s",
                    USE_GPU, _gpu_info["reason"])
        log.warning("Falling back to CPU rather than failing.")
    else:
        log.info("Running on CPU: %s", _gpu_info["reason"])
    if _gpu_info["advice"]:
        log.info("  -> %s", _gpu_info["advice"])
    return False


def _tune_cpu_threads() -> None:
    """Let torch use all cores. Matters a lot for CPU inference."""
    try:
        import torch

        n = os.cpu_count() or 1
        torch.set_num_threads(n)
        log.info("torch CPU threads set to %d", n)
    except Exception as exc:
        log.warning("Could not set torch thread count: %s", exc)


def _tune_gpu() -> None:
    """cuDNN autotuning helps because CellPose feeds fixed-size tiles."""
    try:
        import torch

        torch.backends.cudnn.benchmark = True
        log.info("cuDNN autotuning enabled")
    except Exception as exc:
        log.warning("Could not enable cuDNN autotuning: %s", exc)


def load_model():
    """Load CellPose once. Called at startup."""
    global _model, _device
    from cellpose import models

    gpu = _resolve_gpu()
    if gpu:
        _tune_gpu()
    else:
        _tune_cpu_threads()

    # A custom model is loaded with pretrained_model=<path>; a built-in one
    # with model_type=<name>. Passing a path as model_type does not work.
    is_custom = os.sep in MODEL_TYPE or os.path.exists(MODEL_TYPE)
    if is_custom and not os.path.isfile(MODEL_TYPE):
        raise RuntimeError(
            "CELLCOUNT_MODEL looks like a path but no file is there: %s\n"
            "Copy your trained model to the server and point CELLCOUNT_MODEL "
            "at it." % MODEL_TYPE)

    t0 = time.time()
    try:
        if is_custom:
            log.info("Loading CUSTOM model: %s", MODEL_TYPE)
            _model = models.CellposeModel(gpu=gpu, pretrained_model=MODEL_TYPE)
        else:
            _model = models.CellposeModel(gpu=gpu, model_type=MODEL_TYPE)
    except Exception as exc:
        # CellPose downloads weights from cellpose.org on first use. On a server
        # with no internet -- common for an isolated analysis machine -- this
        # fails with a DNS or connection error and the worker dies at startup,
        # which the Pi sees only as "connection refused".
        text = str(exc).lower()
        looks_like_network = any(k in text for k in (
            "name resolution", "urlopen", "connection", "timed out",
            "temporary failure", "network", "unreachable", "certificate"))
        if looks_like_network:
            log.error("=" * 70)
            log.error("Could not download the CellPose model weights.")
            log.error("Underlying error: %s", exc)
            log.error("")
            log.error("This server has no working internet connection, but the")
            log.error("weights are only needed ONCE. Options:")
            log.error("  1. Connect this machine to the internet briefly and")
            log.error("     restart the worker.")
            log.error("  2. Provision the weights offline:")
            log.error("       python fetch_models.py --pack        (on a machine")
            log.error("                                             WITH internet)")
            log.error("       python fetch_models.py --unpack cellpose_models.tar.gz")
            log.error("  3. Copy an existing ~/.cellpose/models directory across.")
            log.error("=" * 70)
            raise RuntimeError(
                "CellPose model weights unavailable and cannot be downloaded "
                "(no internet). See the instructions above.")
        raise
    _device = "gpu" if gpu else "cpu"
    log.info(
        "Loaded CellPose model '%s' on %s in %.1f s",
        MODEL_TYPE,
        _device,
        time.time() - t0,
    )

    # Log the weights file that was ACTUALLY loaded.
    #
    # CellPose 2's model_type= lookup falls back to the built-in 'cyto' model
    # when it does not recognise a name, without raising. A typo, or a custom
    # model that is not registered in ~/.cellpose/gui_models.txt, therefore
    # yields perfectly plausible counts from the wrong model. Recording the
    # resolved path makes that visible instead of silent.
    loaded = getattr(_model, "pretrained_model", None)
    if isinstance(loaded, (list, tuple)):
        loaded = loaded[0] if loaded else None
    if loaded:
        log.info("  weights file: %s", loaded)
        builtin_names = ("cyto", "cyto2", "cyto3", "nuclei", "tissuenet",
                         "livecell", "bact_phase", "bact_fluor", "deepbacs")
        if not is_custom and MODEL_TYPE not in builtin_names:
            if MODEL_TYPE not in os.path.basename(str(loaded)):
                log.error("=" * 70)
                log.error("REQUESTED model '%s' but CellPose loaded '%s'.",
                          MODEL_TYPE, os.path.basename(str(loaded)))
                log.error("CellPose silently substitutes a built-in model when it")
                log.error("does not recognise the name. Your counts would come")
                log.error("from the WRONG model.")
                log.error("Use an absolute path in CELLCOUNT_MODEL instead.")
                log.error("=" * 70)
                raise RuntimeError(
                    "CellPose substituted '%s' for requested model '%s'. "
                    "Set CELLCOUNT_MODEL to the model file's absolute path."
                    % (os.path.basename(str(loaded)), MODEL_TYPE))

    # A model trained in the GUI records the diameter of the objects it was
    # trained on. Surfacing it removes the guesswork from setting `diameter`.
    for attr in ("diam_labels", "diam_mean"):
        val = getattr(_model, attr, None)
        if val is not None:
            try:
                val = float(np.array(val).mean())
            except Exception:
                continue
            log.info("  model %s = %.2f px", attr, val)
            if attr == "diam_labels" and abs(val - DEFAULT_DIAMETER) > 0.2 * max(val, 1):
                log.warning("  NOTE: configured diameter is %.2f but this model "
                            "was trained at %.2f", DEFAULT_DIAMETER, val)
    return _model


def _filter_kwargs(fn, **kwargs):
    """
    Keep only kwargs the installed CellPose version actually accepts.

    CellPose changed eval()'s signature between 2.x, 3.x and 4.x -- for
    example `net_avg` was removed after 2.x. This keeps the worker working
    across versions instead of raising TypeError.
    """
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return kwargs
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return kwargs
    return {k: v for k, v in kwargs.items() if k in params}


def segment(
    img: np.ndarray,
    diameter: float,
    flow_threshold: float,
    cellprob_threshold: float,
    resample: bool,
    net_avg: bool,
):
    """Run CellPose. Returns (masks, count, seconds)."""
    if _model is None:
        raise RuntimeError("Model not loaded")

    kwargs = _filter_kwargs(
        _model.eval,
        channels=[0, 0],
        diameter=diameter,
        flow_threshold=flow_threshold,
        cellprob_threshold=cellprob_threshold,
        resample=resample,
        net_avg=net_avg,
    )

    t0 = time.time()
    with _model_lock:
        result = _model.eval(img, **kwargs)
    elapsed = time.time() - t0

    masks = result[0]
    # Label 0 is background. Labels are not guaranteed contiguous, so count
    # distinct positive labels rather than trusting masks.max().
    unique = np.unique(masks)
    count = int((unique > 0).sum())
    return masks, count, elapsed


# --------------------------------------------------------------------------
# MASK RENDERING
# --------------------------------------------------------------------------
def _outlines(masks: np.ndarray) -> np.ndarray:
    """Boolean edge map: True where a labelled region borders anything else."""
    o = np.zeros(masks.shape, dtype=bool)
    vdiff = masks[:-1, :] != masks[1:, :]
    hdiff = masks[:, :-1] != masks[:, 1:]
    o[:-1, :] |= vdiff
    o[1:, :] |= vdiff
    o[:, :-1] |= hdiff
    o[:, 1:] |= hdiff
    return o & (masks > 0)


def render_mask(
    masks: np.ndarray,
    original: Optional[np.ndarray],
    overlay: bool,
    max_dim: int,
) -> bytes:
    """
    Render masks to PNG bytes.

    overlay=False -> each cell gets a distinct random colour on black.
                     (Distinct colours, unlike a viridis ramp over label IDs,
                     which makes neighbouring cells nearly identical.)
    overlay=True  -> cell outlines drawn in green over the original image,
                     which is far easier to eyeball for a miscount.
    """
    if overlay and original is not None:
        base = original
        if base.ndim == 2:
            base = np.stack([base] * 3, axis=-1)
        elif base.shape[-1] == 4:
            base = base[..., :3]
        if base.dtype != np.uint8:
            b = base.astype(np.float32)
            lo, hi = float(b.min()), float(b.max())
            base = (
                ((b - lo) / (hi - lo) * 255).astype(np.uint8)
                if hi > lo
                else np.zeros(b.shape, dtype=np.uint8)
            )
        rgb = np.ascontiguousarray(base)
        rgb[_outlines(masks)] = (0, 255, 0)
    else:
        n = int(masks.max())
        rng = np.random.default_rng(0)  # fixed seed -> reproducible colours
        lut = rng.integers(70, 256, size=(n + 1, 3), dtype=np.uint8)
        lut[0] = (0, 0, 0)
        rgb = lut[masks]

    im = Image.fromarray(rgb, mode="RGB")
    if max_dim > 0 and max(im.size) > max_dim:
        scale = max_dim / max(im.size)
        new_size = (max(1, int(im.width * scale)), max(1, int(im.height * scale)))
        # NEAREST, not LANCZOS: interpolating label colours invents cells
        # that are not there.
        im = im.resize(new_size, _NEAREST)

    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
app = FastAPI(title="CellPose Cell Counter Worker", version="1.0")
bearer = HTTPBearer(auto_error=False)


def require_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
) -> None:
    if not AUTH_REQUIRED:
        return
    supplied = credentials.credentials if credentials else ""
    # Constant-time compare so the token cannot be recovered by timing.
    if not secrets.compare_digest(supplied, AUTH_TOKEN):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing token. The token on the Pi must match "
                   "CELLCOUNT_TOKEN on the server.")


@app.on_event("startup")
def _startup() -> None:
    load_model()
    # Warm up: the first inference triggers lazy kernel/cuDNN setup, which
    # would otherwise be charged to the first real sample of the day.
    log.info("Warming up...")
    dummy = (np.random.default_rng(0).random((512, 512)) * 255).astype(np.uint8)
    try:
        _, _, secs = segment(dummy, 25, 0.4, 0.0, True, False)
        log.info("Warm-up inference took %.2f s. Ready.", secs)
    except Exception as exc:
        log.warning("Warm-up failed (non-fatal): %s", exc)


@app.get("/health")
def health():
    """Unauthenticated liveness probe -- returns no sensitive information."""
    return {
        "status": "ok",
        "model": MODEL_TYPE,
        "model_is_custom": os.sep in MODEL_TYPE or os.path.exists(MODEL_TYPE),
        "default_diameter": DEFAULT_DIAMETER,
        "device": _device,
        "loaded": _model is not None,
        "auth_required": AUTH_REQUIRED,
        "gpu": {
            "available": _gpu_info.get("available", False),
            "device_name": _gpu_info.get("device_name"),
            "vram_gb": _gpu_info.get("vram_gb"),
            "torch_version": _gpu_info.get("torch_version"),
            "torch_cuda_build": _gpu_info.get("torch_cuda_build"),
            "reason": _gpu_info.get("reason"),
        },
    }


@app.post("/segment", dependencies=[Depends(require_token)])
async def do_segment(
    file: UploadFile = File(...),
    diameter: float = Form(DEFAULT_DIAMETER),
    flow_threshold: float = Form(DEFAULT_FLOW_THRESHOLD),
    cellprob_threshold: float = Form(DEFAULT_CELLPROB_THRESHOLD),
    mask_max_dim: int = Form(DEFAULT_MASK_MAX_DIM),
    overlay: bool = Form(False),
    resample: bool = Form(True),
    net_avg: bool = Form(False),
):
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Upload too large")
    if not raw:
        raise HTTPException(status_code=400, detail="Empty upload")

    t_total = time.time()
    try:
        pil = Image.open(io.BytesIO(raw))
        pil.load()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Unreadable image: %s" % exc)

    original = np.asarray(pil)
    log.info(
        "Job: %s  %dx%d  %.1f MP  diameter=%.1f",
        file.filename,
        pil.width,
        pil.height,
        pil.width * pil.height / 1e6,
        diameter,
    )

    try:
        masks, count, infer_s = segment(
            original,
            diameter=diameter,
            flow_threshold=flow_threshold,
            cellprob_threshold=cellprob_threshold,
            resample=resample,
            net_avg=net_avg,
        )
    except Exception as exc:
        log.exception("Segmentation failed")
        raise HTTPException(status_code=500, detail="Segmentation failed: %s" % exc)

    png = render_mask(masks, original, overlay=overlay, max_dim=mask_max_dim)
    total_s = time.time() - t_total

    log.info("  -> %d cells, inference %.2f s, total %.2f s", count, infer_s, total_s)

    return {
        "count": count,
        "mask_png_b64": base64.b64encode(png).decode("ascii"),
        "image_width": pil.width,
        "image_height": pil.height,
        "timings": {"inference_s": round(infer_s, 3), "total_s": round(total_s, 3)},
        "params": {
            "model": MODEL_TYPE,
            "device": _device,
            "diameter": diameter,
            "flow_threshold": flow_threshold,
            "cellprob_threshold": cellprob_threshold,
            "resample": resample,
            "net_avg": net_avg,
        },
    }


if __name__ == "__main__":
    # Standalone check:  python worker.py --gpu-check
    import sys

    if "--gpu-check" in sys.argv:
        # check_gpu.py is the standalone version -- it needs only torch, so it
        # still works when the rest of the environment is broken.
        info = gpu_diagnostics()
        print("PyTorch version : %s" % info["torch_version"])
        print("CUDA build      : %s" % (info["torch_cuda_build"] or "none (CPU-only wheel)"))
        if info["available"]:
            print("GPU             : %s" % info["device_name"])
            print("VRAM            : %.1f GB" % info["vram_gb"])
            print("\nGPU acceleration WILL be used.")
        else:
            print("GPU             : not usable")
            print("Reason          : %s" % info["reason"])
            if info["advice"]:
                print("\nHow to fix:\n  %s" % info["advice"])
            print("\nThe worker will run on CPU. That is fine -- expect roughly")
            print("10-25 s per sample instead of 1-3 s.")
        raise SystemExit(0 if info["available"] else 1)

    print("Start the worker with:")
    print("  python -m uvicorn worker:app --host <address> --port 8000")
    print("Check GPU support with:")
    print("  python worker.py --gpu-check")
