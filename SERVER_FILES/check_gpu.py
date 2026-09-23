"""
check_gpu.py -- will CellPose use your NVIDIA GPU?

Deliberately standalone: it imports nothing but torch, so it still works when
the rest of the environment is broken or half-installed. That is exactly when
you need it.

    python check_gpu.py

Catches the common trap of installing the CPU-only PyTorch wheel on a machine
that has a perfectly good GPU. torch.cuda.is_available() returns False, the
worker quietly runs on CPU, and nothing tells you why it is slow.
"""

from __future__ import print_function


def diagnose():
    info = {"available": False, "reason": None, "device_name": None,
            "torch_version": None, "torch_cuda_build": None,
            "vram_gb": None, "advice": None, "compute_capability": None,
            "torch_arch_list": None}
    try:
        import torch
    except ImportError:
        info["reason"] = "torch is not installed in this environment"
        info["advice"] = ("Activate the right environment first "
                          "(conda activate cellcount), then install PyTorch.")
        return info

    info["torch_version"] = torch.__version__
    info["torch_cuda_build"] = torch.version.cuda

    if torch.version.cuda is None:
        info["reason"] = "this PyTorch is a CPU-only build (no CUDA compiled in)"
        info["advice"] = (
            "If this machine has an NVIDIA GPU, reinstall from a CUDA index:\n"
            "    pip install --force-reinstall torch \\\n"
            "        --index-url https://download.pytorch.org/whl/cu128\n"
            "  Pick cu126 / cu128 / cu130 to match the CUDA version that\n"
            "  'nvidia-smi' reports (choose one no higher than that).")
        return info

    try:
        if not torch.cuda.is_available():
            info["reason"] = ("PyTorch has CUDA support, but no usable GPU was "
                              "found")
            info["advice"] = (
                "Run 'nvidia-smi'.\n"
                "  * Command not found or errors  -> install the NVIDIA driver.\n"
                "  * Reports a CUDA version below %s -> install a lower PyTorch\n"
                "    CUDA wheel, or update the driver." % torch.version.cuda)
            return info

        name = torch.cuda.get_device_name(0)
        major, minor = torch.cuda.get_device_capability(0)
        info["device_name"] = name
        info["compute_capability"] = "%d.%d" % (major, minor)
        info["vram_gb"] = round(
            torch.cuda.get_device_properties(0).total_memory / (1024 ** 3), 1)

        # is_available() is not enough: recent PyTorch CUDA builds ship kernels
        # only for newer architectures, so an older card can be "available" and
        # still have no usable kernels.
        try:
            arch_list = torch.cuda.get_arch_list()
        except Exception:
            arch_list = []
        info["torch_arch_list"] = arch_list

        if arch_list:
            dev_val = major * 10 + minor
            usable = any(
                a.startswith("sm_") and a[3:].isdigit()
                and int(a[3:]) // 10 == major and int(a[3:]) <= dev_val
                for a in arch_list)
            if not usable:
                info["reason"] = (
                    "this GPU is compute capability %d.%d (sm_%d%d), but the "
                    "installed PyTorch only has kernels for: %s"
                    % (major, minor, major, minor, ", ".join(arch_list)))
                info["advice"] = (
                    "Install a CUDA build that supports sm_%d%d -- an older\n"
                    "  index such as cu126 usually does:\n"
                    "    pip install --force-reinstall torch \\\n"
                    "        --index-url https://download.pytorch.org/whl/cu126\n"
                    "  Or set CELLCOUNT_GPU=0 and run on CPU: for this workload\n"
                    "  that costs only seconds per sample."
                    % (major, minor))
                return info

        info["available"] = True
        return info
    except Exception as exc:
        info["reason"] = "CUDA check raised: %s" % exc
        info["advice"] = "Run 'nvidia-smi' to confirm the driver works."
        return info


def main():
    info = diagnose()
    print("=" * 62)
    print("CellPose GPU check")
    print("=" * 62)
    print("  PyTorch version : %s" % (info["torch_version"] or "not installed"))
    print("  CUDA build      : %s"
          % (info["torch_cuda_build"] or "none (CPU-only wheel)"))

    if info["compute_capability"]:
        print("  GPU             : %s" % info["device_name"])
        print("  Compute cap.    : %s" % info["compute_capability"])
        if info["vram_gb"]:
            print("  VRAM            : %.1f GB" % info["vram_gb"])

    if info["available"]:
        print("")
        if info["vram_gb"] < 2:
            print("  NOTE: under 2 GB of VRAM. Should still be fine for 2 MP")
            print("        images, but watch for out-of-memory errors.")
            print("")
        print("  GPU acceleration WILL be used.")
        print("  Expect roughly 1-3 s per sample instead of 10-25 s.")
        return 0

    if not info["compute_capability"]:
        print("  GPU             : not usable")
    else:
        print("  Usable          : NO")
    print("  Reason          : %s" % info["reason"])
    print("")
    if info["advice"]:
        print("How to fix:")
        for line in info["advice"].split("\n"):
            print("  %s" % line)
        print("")
    print("The worker will run on CPU. For this workload that is perfectly")
    print("usable -- roughly 10-25 s per sample on a modern CPU.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
