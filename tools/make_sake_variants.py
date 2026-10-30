"""Build the held-note ("sake") test workflows from the baseline workflow.

Cuts 9.0 s to 15.0 s from the vocal, then writes one workflow per variant.
Each variant changes only audio_scale or audio_cfg_scale. All use the emotion prompt and seed 2.
"""
import copy
import json
import wave

SRC_WAV = r"D:\Project_lip_service\inputs\RingTheBell.wav"
CLIP_NAME = "lipservice_sake_6s.wav"
CLIP_PATH = r"D:\Comfy-Desktop\ComfyUI-Shared\input" + "\\" + CLIP_NAME
BASE = r"D:\Project_lip_service\workflows\baseline_single_api.json"
OUT_DIR = r"D:\Project_lip_service\workflows"

START_S, LENGTH_S, FPS = 9.0, 6.0, 25

EMOTION_PROMPT = (
    "a woman in a black hooded cloak sings with raw emotion in a colonial market square, "
    "eyes closing on the held note, brows drawn together in anguish, chest lifting as she breathes in, "
    "head tilting back on the high note, her hands tightening on the basket of apples, "
    "expressive face, natural head and shoulder movement"
)

VARIANTS = {
    "sake_a_scale1.5": {"audio_scale": 1.5, "audio_cfg_scale": 1.0},
    "sake_b_scale2.0": {"audio_scale": 2.0, "audio_cfg_scale": 1.0},
    "sake_c_cfg2.5": {"audio_scale": 1.0, "audio_cfg_scale": 2.5},
}


def cut_clip():
    w = wave.open(SRC_WAV)
    sr = w.getframerate()
    w.setpos(int(START_S * sr))
    data = w.readframes(int(LENGTH_S * sr))
    o = wave.open(CLIP_PATH, "wb")
    o.setnchannels(w.getnchannels())
    o.setsampwidth(w.getsampwidth())
    o.setframerate(sr)
    o.writeframes(data)
    o.close()
    print("wrote", CLIP_PATH)


def main():
    cut_clip()
    base = json.load(open(BASE, encoding="utf8"))
    for name, vals in VARIANTS.items():
        wf = copy.deepcopy(base)
        wf["6"]["inputs"]["audio"] = CLIP_NAME
        emb = wf["8"]["inputs"]
        emb["num_frames"] = int(LENGTH_S * FPS)
        emb["audio_scale"] = vals["audio_scale"]
        emb["audio_cfg_scale"] = vals["audio_cfg_scale"]
        wf["13"]["inputs"]["positive_prompt"] = EMOTION_PROMPT
        wf["17"]["inputs"]["filename_prefix"] = "lipservice/" + name
        path = f"{OUT_DIR}\\{name}_api.json"
        json.dump(wf, open(path, "w", encoding="utf8"), indent=2)
        print("wrote", path)


main()
