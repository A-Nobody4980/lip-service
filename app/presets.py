"""Render presets.

BASELINE is the exact setup that worked on the RTX 5070 (12 GB) in the Oct 26 baseline test.
It is the default and must not change without the project owner's say so.
"""
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Preset:
    name: str
    width: int = 832
    height: int = 480
    fps: int = 25
    steps: int = 6
    cfg: float = 1.0
    shift: float = 11.0
    scheduler: str = "dpm++_sde"
    seed: int = 2
    blocks_to_swap: int = 20
    audio_scale: float = 1.0
    audio_cfg_scale: float = 1.0
    frame_window_size: int = 81
    motion_frame: int = 9
    lora_strength: float = 1.0


BASELINE = Preset(name="baseline")

# Output sizes per aspect ratio: about 400,000 pixels (832x480 is 399,360), each side a multiple of 16, which is
# the size class the Wan 2.1 480P model works at. Every ratio listed here has to work on the 12 GB test card:
# one that fails its test render is removed from this list, so the screen never shows a button that does not work.
ASPECTS = {
    "16:9": {"width": 832, "height": 480},
    "9:16": {"width": 480, "height": 832},
    "1:1": {"width": 640, "height": 640},
    "4:3": {"width": 704, "height": 528},
}

# Quality positions on the screen. Default is the baseline, untouched. Fast is the baseline with 4 steps.
# Best has the baseline's settings too (6 steps, shift 11): only the base model (Q6_K) and the block swap change,
# and those are chosen when the job runs (see runner.settings_for).
FAST = replace(BASELINE, name="fast", steps=4)
BEST = replace(BASELINE, name="best")
BEST_MODEL = r"WanVideo\wan2.1-i2v-14b-480p-Q6_K.gguf"
QUALITY_POSITIONS = (("fast", 0.0, "Fast draft"), ("default", 0.5, "Default"), ("best", 1.0, "Best"))
QUALITY_PRESET = {"fast": "fast", "default": "baseline", "best": "best"}


def quality_id(value) -> str:
    """The position nearest to a slider value."""
    v = 0.5 if value is None else float(value)
    return min(QUALITY_POSITIONS, key=lambda p: abs(p[1] - v))[0]


PRESETS = {"baseline": BASELINE, "fast": FAST, "best": BEST}
DEFAULT_PRESET = "baseline"


def get_preset(name: str = DEFAULT_PRESET, **overrides) -> Preset:
    preset = PRESETS[name]
    return replace(preset, **overrides) if overrides else preset
