"""What the PC can take: GPU memory (for block swap) and free RAM (for the Best quality warning)."""
import math
import subprocess

import psutil

REF_PIXELS = 832 * 480               # the tested frame size (399,360 pixels)
BLOCKS = 40                        # transformer blocks in the Wan 2.1 14B model
REF_VRAM_MIB = 12227               # the RTX 5070 the default look was tuned on (nvidia-smi memory.total)
REF_MODEL_GB = 11.3412             # wan2.1-i2v-14b-480p-Q4_K_M.gguf
REF_RESIDENT_GB = REF_MODEL_GB / 2  # weights kept on the card at the default 20 of 40 blocks swapped
EXTRA_RESIDENT_PER_GB = 0.9        # each extra GB of card memory keeps about this much more of the model on the card
RAM_NEEDED_GB = 22                 # free RAM to start with: a render peaks near 26 GB on the 32 GB test PC in every mode


def vram_mib():
    """Total memory of the first NVIDIA card, or None if nvidia-smi cannot say."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout.strip().splitlines()
        return int(out[0])
    except Exception:
        return None


def blocks_to_swap(model_bytes, vram=None, pixels=REF_PIXELS):
    """How many of the 40 blocks to keep in system RAM so the rest fits on the card. Calibrated so the default
    Q4_K_M base on the 12 GB RTX 5070 gives exactly 20, the tested setting. A bigger model swaps more, a bigger
    card swaps less. An unknown card is treated like the reference card (the most careful choice)."""
    vram = vram or REF_VRAM_MIB
    budget_gb = REF_RESIDENT_GB + (vram - REF_VRAM_MIB) / 1024 * EXTRA_RESIDENT_PER_GB
    size_gb = model_bytes / 1e9
    swap = math.ceil(BLOCKS * (1 - budget_gb / size_gb) - 0.01)
    if swap > 0 and pixels > REF_PIXELS * 1.005:  # a bigger frame needs more room for the work, so keep one more block off the card
        swap += 1
    return max(0, min(BLOCKS, swap))


def ram_status():
    free = psutil.virtual_memory().available / 1e9
    return {"ram_free_gb": round(free, 1), "ram_needed_gb": RAM_NEEDED_GB, "ram_ok": free >= RAM_NEEDED_GB}
