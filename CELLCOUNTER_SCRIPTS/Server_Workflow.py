"""
Server_Workflow.py -- drop-in replacement for Github_Workflow.py.

Sends the tiled microscope image to the analysis server over HTTPS, waits for
the segmentation result, and writes the mask PNG and the cell count to exactly
the same local paths the old GitHub workflow used. Cell_Counter_Main.py
therefore needs only its import line changed.

Compatible with Python 3.7 (the OpenFlexure client requires it).

Configuration -- no secrets in this file. Set either:

  (a) environment variables:
        CELLCOUNT_URL=https://your-server.example/segment
        CELLCOUNT_TOKEN=<the shared secret>

  (b) or a config file at ~/.cell_counter/server.conf:
        url = https://your-server.example
        token = <the shared secret>
        diameter = 25
        overlay = false
"""

from __future__ import print_function

import base64
import os
import sys
import time

import numpy as np
import requests

# --------------------------------------------------------------------------
# Paths -- unchanged from the GitHub version so the GUI keeps working.
# --------------------------------------------------------------------------
BASE_DIR = "/home/openflexure/Applications/Cell_Counter"
LOCAL_IMAGE_PATH = os.path.join(BASE_DIR, "chosen_image", "chosen_image.tiff")
PROCESSED_IMAGE_PATH = os.path.join(BASE_DIR, "workflow_files", "image_mask.png")
PROCESSED_TEXT_PATH = os.path.join(BASE_DIR, "workflow_files", "cell_number.txt")

CONFIG_PATH = os.path.expanduser("~/.cell_counter/server.conf")

# Network behaviour
CONNECT_TIMEOUT = 10      # seconds to establish the connection
READ_TIMEOUT = 300        # seconds to wait for segmentation to finish
MAX_ATTEMPTS = 3          # retries on transient network failures
RETRY_BACKOFF = 2.0       # seconds, doubled each attempt


class ServerError(RuntimeError):
    """Raised when the analysis server cannot produce a result."""


# --------------------------------------------------------------------------
# Configuration loading
# --------------------------------------------------------------------------
def _read_config_file(path):
    cfg = {}
    if not os.path.exists(path):
        return cfg
    with open(path, "r") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            cfg[key.strip().lower()] = value.strip()
    return cfg


def load_config():
    """Environment variables win over the config file."""
    cfg = _read_config_file(CONFIG_PATH)

    url = os.getenv("CELLCOUNT_URL", cfg.get("url", "")).rstrip("/")
    token = os.getenv("CELLCOUNT_TOKEN", cfg.get("token", ""))

    if not url:
        raise ServerError(
            "No server URL configured. Set CELLCOUNT_URL or add 'url = ...' to "
            + CONFIG_PATH
        )
    if not token:
        raise ServerError(
            "No auth token configured. Set CELLCOUNT_TOKEN or add 'token = ...' "
            "to " + CONFIG_PATH
        )

    # Accept either the bare host or the full endpoint.
    if not url.endswith("/segment"):
        url = url + "/segment"

    def _num(key, default, cast):
        try:
            return cast(cfg.get(key, default))
        except (TypeError, ValueError):
            return cast(default)

    return {
        "url": url,
        "token": token,
        "diameter": _num("diameter", 15.328, float),
        "flow_threshold": _num("flow_threshold", 0.4, float),
        "cellprob_threshold": _num("cellprob_threshold", 0.0, float),
        "mask_max_dim": _num("mask_max_dim", 1200, int),
        "overlay": str(cfg.get("overlay", "false")).lower() in ("1", "true", "yes"),
        "flatfield": str(cfg.get("flatfield", "true")).lower() not in ("0", "false", "no"),
        "flatfield_path": cfg.get("flatfield_path", "") or None,
        "save_corrected": str(cfg.get("save_corrected", "true")).lower()
        not in ("0", "false", "no"),
        "verify_tls": str(cfg.get("verify_tls", "true")).lower()
        not in ("0", "false", "no"),
    }


# --------------------------------------------------------------------------
# Core request
# --------------------------------------------------------------------------
def _post_image(cfg, image_path, status_callback):
    headers = {"Authorization": "Bearer " + cfg["token"]}
    data = {
        "diameter": str(cfg["diameter"]),
        "flow_threshold": str(cfg["flow_threshold"]),
        "cellprob_threshold": str(cfg["cellprob_threshold"]),
        "mask_max_dim": str(cfg["mask_max_dim"]),
        "overlay": "true" if cfg["overlay"] else "false",
    }

    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if status_callback:
            status_callback("Uploading image (attempt %d)..." % attempt)
        try:
            # Reopen per attempt: a retried upload must restart from byte 0.
            with open(image_path, "rb") as fh:
                files = {"file": (os.path.basename(image_path), fh, "image/tiff")}
                response = requests.post(
                    cfg["url"],
                    headers=headers,
                    data=data,
                    files=files,
                    timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                    verify=cfg["verify_tls"],
                )
        except requests.exceptions.RequestException as exc:
            last_error = exc
            if attempt < MAX_ATTEMPTS:
                wait = RETRY_BACKOFF * (2 ** (attempt - 1))
                print("Network error: %s -- retrying in %.0f s" % (exc, wait))
                if status_callback:
                    status_callback("Network error, retrying...")
                time.sleep(wait)
                continue
            raise ServerError(
                "Could not reach the analysis server at %s after %d attempts: %s"
                % (cfg["url"], MAX_ATTEMPTS, last_error)
            )

        if response.status_code == 401:
            raise ServerError(
                "Server rejected the auth token (401). Check that the token on "
                "the Pi matches CELLCOUNT_TOKEN on the server."
            )
        if response.status_code != 200:
            # 5xx can be transient; 4xx will not fix itself.
            if 500 <= response.status_code < 600 and attempt < MAX_ATTEMPTS:
                wait = RETRY_BACKOFF * (2 ** (attempt - 1))
                print("Server error %d -- retrying in %.0f s" % (response.status_code, wait))
                time.sleep(wait)
                continue
            raise ServerError(
                "Server returned HTTP %d: %s"
                % (response.status_code, response.text[:300])
            )

        if status_callback:
            status_callback("Segmenting...")
        try:
            return response.json()
        except ValueError:
            raise ServerError("Server returned a non-JSON response")

    raise ServerError("Exhausted retries: %s" % last_error)


def _write_atomic(path, payload_bytes):
    """Write via a temp file + rename so a crash never leaves a partial file."""
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    tmp = path + ".part"
    with open(tmp, "wb") as fh:
        fh.write(payload_bytes)
    os.rename(tmp, path)


def _flatfield_corrected(image_path, ff_path=None, save_copy=True):
    """
    Apply illumination correction before upload, returning a path to send.

    Done here rather than on the server because the reference describes THIS
    microscope's optics -- see Flatfield.py. Costs ~0.1 s on a Pi 4B.

    Returns (path_to_upload, temp_file_or_None). Any problem falls back to
    sending the original image, and ALWAYS says so -- a silent fallback would
    let you believe correction was happening when it was not.
    """
    try:
        import cv2
        import Flatfield
    except ImportError as exc:
        print("  [flat-field] SKIPPED: %s not installed. Sending raw image." % exc.name)
        return image_path, None

    path = ff_path or Flatfield.DEFAULT_FLATFIELD_PATH
    if not os.path.exists(path):
        print("  [flat-field] SKIPPED: no reference at %s" % path)
        print("               Create one with: python3 make_flatfield.py --capture 16")
        return image_path, None

    try:
        colour = cv2.imread(image_path, cv2.IMREAD_COLOR)
        if colour is None:
            print("  [flat-field] SKIPPED: could not read %s" % image_path)
            return image_path, None
        gray = cv2.cvtColor(colour, cv2.COLOR_BGR2GRAY)

        before = float(cv2.GaussianBlur(gray.astype(np.float32), (0, 0), 40).std())
        corrected = Flatfield.apply_uint8(gray, path=ff_path)
        after = float(cv2.GaussianBlur(corrected.astype(np.float32), (0, 0), 40).std())

        tmp = os.path.join(os.path.dirname(image_path), "_corrected_upload.tiff")
        if not cv2.imwrite(tmp, corrected):
            print("  [flat-field] SKIPPED: could not write %s" % tmp)
            return image_path, None

        print("  [flat-field] APPLIED using %s" % path)
        print("               background variation %.1f -> %.1f (%.1fx flatter)"
              % (before, after, before / max(after, 1e-6)))

        # Keep an inspectable copy alongside the raw image. The RAW image is
        # never overwritten: correction is not invertible, and you may want to
        # reprocess later with a better reference.
        if save_copy:
            # Written to workflow_files/, NOT next to chosen_image.tiff --
            # stray files in the capture directory could confuse anything that
            # lists it. The RAW image is never overwritten: correction is not
            # invertible and you may want to reprocess with a better reference.
            keep = os.path.join(os.path.dirname(PROCESSED_IMAGE_PATH),
                                "chosen_image_corrected.tiff")
            keep_dir = os.path.dirname(keep)
            if keep_dir and not os.path.isdir(keep_dir):
                os.makedirs(keep_dir)
            cv2.imwrite(keep, corrected)

        return tmp, tmp
    except Exception as exc:
        print("  [flat-field] SKIPPED: %s. Sending raw image." % exc)
        return image_path, None


# --------------------------------------------------------------------------
# Public API -- same name and call signature as the GitHub version
# --------------------------------------------------------------------------
def Process_Images(image_path=None, status_callback=None):
    """
    Upload the chosen image, run segmentation on the server, and save results.

    Writes PROCESSED_IMAGE_PATH (mask PNG) and PROCESSED_TEXT_PATH (count),
    then returns the cell count as an int.
    """
    image_path = image_path or LOCAL_IMAGE_PATH
    if not os.path.exists(image_path):
        raise ServerError("Image not found: %s" % image_path)

    cfg = load_config()
    t0 = time.time()

    tmp = None
    upload_path = image_path
    if cfg["flatfield"]:
        if status_callback:
            status_callback("Correcting illumination...")
        upload_path, tmp = _flatfield_corrected(
            image_path, cfg["flatfield_path"], cfg["save_corrected"])

    try:
        size_mb = os.path.getsize(upload_path) / 1e6
        print("Sending %s (%.1f MB) to %s" % (upload_path, size_mb, cfg["url"]))
        result = _post_image(cfg, upload_path, status_callback)
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass

    count = int(result["count"])
    mask_png = base64.b64decode(result["mask_png_b64"])

    _write_atomic(PROCESSED_IMAGE_PATH, mask_png)
    _write_atomic(PROCESSED_TEXT_PATH, str(count).encode("utf-8"))

    timings = result.get("timings", {})
    print(
        "Counted %d cells | server inference %.2f s | round trip %.2f s | device %s"
        % (
            count,
            timings.get("inference_s", float("nan")),
            time.time() - t0,
            result.get("params", {}).get("device", "?"),
        )
    )

    if status_callback:
        status_callback("Done: %d cells" % count)
    return count


def check_server():
    """Ping /health. Returns True if the server is up. Never raises."""
    try:
        cfg = load_config()
    except ServerError as exc:
        print("Config problem: %s" % exc)
        return False

    health_url = cfg["url"].rsplit("/segment", 1)[0] + "/health"
    try:
        r = requests.get(health_url, timeout=(CONNECT_TIMEOUT, 15),
                         verify=cfg["verify_tls"])
        if r.status_code == 200:
            print("Server healthy: %s" % r.json())
            return True
        print("Server unhealthy: HTTP %d" % r.status_code)
    except requests.exceptions.RequestException as exc:
        print("Cannot reach server: %s" % exc)
    return False


if __name__ == "__main__":
    if not check_server():
        sys.exit(1)
    if os.path.exists(LOCAL_IMAGE_PATH):
        Process_Images(status_callback=lambda msg: print("  [%s]" % msg))
    else:
        print("No image at %s -- health check only." % LOCAL_IMAGE_PATH)
