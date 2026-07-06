"""CUDA device checks for Blackwell (sm_120) and older GPUs."""

from __future__ import annotations


def cuda_device_usable(device: str | None) -> bool:
    """False when PyTorch lacks kernels for the installed GPU (e.g. RTX 5090 + cu124)."""
    if not device or not str(device).lower().startswith("cuda"):
        return True
    try:
        import torch
    except ImportError:
        return False
    if not torch.cuda.is_available():
        return False
    try:
        cap = torch.cuda.get_device_capability(0)
        arch = f"sm_{cap[0]}{cap[1]}"
        supported = set(getattr(torch.cuda, "get_arch_list", lambda: [])())
        if supported and arch not in supported:
            return False
        # Smoke test — catches "no kernel image" even when capability looks fine.
        torch.zeros(1, device="cuda")
        return True
    except Exception:  # noqa: BLE001
        return False


def resolve_torch_device(requested: str | None, *, label: str = "model") -> str:
    """Use requested device, or fall back to CPU with a clear log when CUDA won't run."""
    import logging

    log = logging.getLogger("voice-agent.cuda")
    device = (requested or "cuda").strip()
    if device.lower().startswith("cuda") and not cuda_device_usable(device):
        try:
            import torch

            cap = torch.cuda.get_device_capability(0)
            name = torch.cuda.get_device_name(0)
            arch = f"sm_{cap[0]}{cap[1]}"
            log.warning(
                "%s: %s (%s) is not supported by torch %s (CUDA %s). "
                "Install torch+cu128 for RTX 50-series, or set VA_TTS_DEVICE=cpu.",
                label,
                name,
                arch,
                torch.__version__,
                torch.version.cuda,
            )
        except Exception:  # noqa: BLE001
            log.warning("%s: CUDA unavailable — falling back to CPU.", label)
        return "cpu"
    return device
