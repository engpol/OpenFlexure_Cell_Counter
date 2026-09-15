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

if not AUTH_TOKEN:
    AUTH_TOKEN = secrets.token_urlsafe(32)
    log.warning("=" * 70)
    log.warning("CELLCOUNT_TOKEN was not set. Generated an ephemeral token:")
    log.warning("    %s", AUTH_TOKEN)
    log.warning("This changes every restart. Set CELLCOUNT_TOKEN for a stable one.")
    log.warning("=" * 70)

# --------------------------------------------------------------------------
# MODEL
# --------------------------------------------------------------------------
_model = None
_model_lock = threading.Lock()  # CellPose models are not thread-safe.
_device = "unknown"


def _resolve_gpu() -> bool:
    if USE_GPU in ("1", "true", "yes"):
        return True
    if USE_GPU in ("0", "false", "no"):
        return False
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
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


def load_model():
    """Load CellPose once. Called at startup."""
    global _model, _device
    from cellpose import models

    gpu = _resolve_gpu()
    if not gpu:
        _tune_cpu_threads()

    t0 = time.time()
    _model = models.CellposeModel(gpu=gpu, model_type=MODEL_TYPE)
    _device = "gpu" if gpu else "cpu"
    log.info(
        "Loaded CellPose model '%s' on %s in %.1f s",
        MODEL_TYPE,
        _device,
        time.time() - t0,
    )
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
    supplied = credentials.credentials if credentials else ""
    # Constant-time compare so the token cannot be recovered by timing.
    if not secrets.compare_digest(supplied, AUTH_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid or missing token")


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
        "device": _device,
        "loaded": _model is not None,
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
