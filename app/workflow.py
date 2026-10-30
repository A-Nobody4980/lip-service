"""Build a ComfyUI API-format workflow from the baseline template.

The template is workflows/baseline_single_api.json (nodes 1 to 17). Only the values that
belong to a job or a preset are patched. Everything else stays exactly as tested.
"""
import copy
import json
import math
from pathlib import Path

from .presets import Preset

TEMPLATE = Path(__file__).resolve().parent.parent / "workflows" / "baseline_single_api.json"
MELBAND_MODEL = r"MelBandRoFormer\MelBandRoformer_fp16.safetensors"

DEFAULT_PROMPT = (
    "a person sings passionately, expressive face, emotional performance, "
    "natural head and shoulder movement"
)
DEFAULT_NEGATIVE = (
    "bright tones, overexposed, static, blurred details, subtitles, style, works, paintings, "
    "images, static, overall gray, worst quality, low quality, JPEG compression residue, ugly, "
    "incomplete, extra fingers, poorly drawn hands, poorly drawn faces, deformed, disfigured, "
    "misshapen limbs, fused fingers, still picture, messy background, three legs, "
    "many people in the background, walking backwards"
)


def frame_count(duration_s: float, fps: int) -> int:
    return max(1, math.ceil(duration_s * fps))


def build_single(
    image_name: str,
    audio_name: str,
    duration_s: float,
    prefix: str,
    preset: Preset,
    prompt: str = DEFAULT_PROMPT,
    negative_prompt: str = DEFAULT_NEGATIVE,
    isolate_vocals: bool = False,
    model: str | None = None,
) -> dict:
    wf = json.loads(TEMPLATE.read_text(encoding="utf-8-sig"))
    wf = copy.deepcopy(wf)
    frames = frame_count(duration_s, preset.fps)

    wf["1"]["inputs"]["image"] = image_name
    wf["2"]["inputs"].update(width=preset.width, height=preset.height)
    wf["6"]["inputs"]["audio"] = audio_name

    emb = wf["8"]["inputs"]
    emb.update(num_frames=frames, fps=preset.fps, audio_scale=preset.audio_scale,
               audio_cfg_scale=preset.audio_cfg_scale)

    if model:
        wf["12"]["inputs"]["model"] = model
    wf["10"]["inputs"]["strength"] = preset.lora_strength
    wf["11"]["inputs"]["blocks_to_swap"] = preset.blocks_to_swap
    wf["13"]["inputs"]["positive_prompt"] = prompt
    wf["13"]["inputs"]["negative_prompt"] = negative_prompt
    wf["14"]["inputs"].update(width=preset.width, height=preset.height,
                              frame_window_size=preset.frame_window_size,
                              motion_frame=preset.motion_frame)
    wf["15"]["inputs"].update(steps=preset.steps, cfg=preset.cfg, shift=preset.shift,
                              seed=preset.seed, scheduler=preset.scheduler)

    if isolate_vocals:
        wf["20"] = {"class_type": "MelBandRoFormerModelLoader",
                    "inputs": {"model_name": MELBAND_MODEL}}
        wf["21"] = {"class_type": "MelBandRoFormerSampler",
                    "inputs": {"model": ["20", 0], "audio": ["6", 0]}}
        emb["audio_1"] = ["21", 0]

    # The sampler pads the video to whole windows. Cut to the audio length, then let the
    # app mux the original audio back on (the video file itself carries no audio).
    wf["18"] = {"class_type": "ImageFromBatch",
                "inputs": {"image": ["16", 0], "batch_index": 0, "length": frames}}
    out = wf["17"]["inputs"]
    out["images"] = ["18", 0]
    out["frame_rate"] = preset.fps
    out["filename_prefix"] = prefix
    out.pop("audio", None)
    return wf


MULTI_MODEL = r"WanVideo\InfiniteTalk\Wan2_1-InfiniteTalk_Multi_Q8.gguf"
MAX_SINGERS = 4


def build_multi(
    image_name: str,
    audio_names: list[str],
    mask_names: list[str],
    duration_s: float,
    prefix: str,
    preset: Preset,
    prompt: str = DEFAULT_PROMPT,
    negative_prompt: str = DEFAULT_NEGATIVE,
    isolate_vocals: bool = False,
    model: str | None = None,
) -> dict:
    """Several singers in one shot. One audio slot and one mask per entry (slots 1 to 4).

    Pass the same audio file in every slot for a unison part. Pass one audio file and one mask
    that covers a whole group to drive the group from a single slot. A last extra mask, if given, is the
    background: whoever is in it is given to nobody.
    """
    if not 1 <= len(audio_names) <= MAX_SINGERS:
        raise ValueError(f"1 to {MAX_SINGERS} audio slots, got {len(audio_names)}")
    if len(mask_names) not in (len(audio_names), len(audio_names) + 1):
        raise ValueError("one mask per audio slot, plus an optional last mask for the background")
    wf = build_single(image_name, audio_names[0], duration_s, prefix, preset, prompt,
                      negative_prompt, isolate_vocals, model=model)
    wf["9"]["inputs"]["model"] = MULTI_MODEL
    emb = wf["8"]["inputs"]

    # slot 1 keeps node 6 (and the isolation node 21 when on). Other slots load their own audio,
    # or reuse slot 1 when the file is the same.
    slot_source = {audio_names[0]: emb["audio_1"]}
    for i, name in enumerate(audio_names[1:], start=2):
        if name not in slot_source:
            node = str(50 + i)
            wf[node] = {"class_type": "LoadAudio", "inputs": {"audio": name}}
            src = [node, 0]
            if isolate_vocals:
                sep = str(60 + i)
                wf[sep] = {"class_type": "MelBandRoFormerSampler",
                           "inputs": {"model": ["20", 0], "audio": src}}
                src = [sep, 0]
            slot_source[name] = src
        emb[f"audio_{i}"] = slot_source[name]

    masks = {}
    for i, name in enumerate(mask_names):
        node = str(30 + i)
        wf[node] = {"class_type": "LoadImageMask", "inputs": {"image": name, "channel": "red"}}
        masks[f"masks.mask{i}"] = [node, 0]
    wf["40"] = {"class_type": "BatchMasksNode", "inputs": masks}
    emb["ref_target_masks"] = ["40", 0]
    return wf
