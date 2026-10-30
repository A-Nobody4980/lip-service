"""Build the 3.2 s no-LoRA vowel test from the baseline workflow.

Cuts 10.0 s to 13.24 s of the vocal (the held "sake" note, one 81 frame window) and
removes the speed LoRA. With no LoRA the text cfg and the negative prompt are in play,
so steps, cfg, shift and scheduler change. Everything else matches the baseline.
Block swap is 26 here because cfg above 1.0 and audio cfg add model passes.
"""
import json
import wave

SRC_WAV = r"D:\Project_lip_service\inputs\RingTheBell.wav"
CLIP_NAME = "lipservice_vowel_3s.wav"
CLIP_PATH = r"D:\Comfy-Desktop\ComfyUI-Shared\input" + "\\" + CLIP_NAME
BASE = r"D:\Project_lip_service\workflows\baseline_single_api.json"
OUT = r"D:\Project_lip_service\workflows\vowel_nolora_api.json"

START_S, FRAMES, FPS = 10.0, 81, 25

EMOTION_PROMPT = (
    "a woman in a black hooded cloak sings with raw emotion in a colonial market square, "
    "eyes closing on the held note, brows drawn together in anguish, chest lifting as she breathes in, "
    "head tilting back on the high note, her hands tightening on the basket of apples, "
    "expressive face, natural head and shoulder movement"
)


def cut_clip():
    w = wave.open(SRC_WAV)
    sr = w.getframerate()
    w.setpos(int(START_S * sr))
    data = w.readframes(int(FRAMES / FPS * sr))
    o = wave.open(CLIP_PATH, "wb")
    o.setnchannels(w.getnchannels())
    o.setsampwidth(w.getsampwidth())
    o.setframerate(sr)
    o.writeframes(data)
    o.close()
    print("wrote", CLIP_PATH)


def main():
    cut_clip()
    wf = json.load(open(BASE, encoding="utf8"))
    wf["6"]["inputs"]["audio"] = CLIP_NAME
    emb = wf["8"]["inputs"]
    emb["num_frames"] = FRAMES
    emb["audio_scale"] = 1.0
    emb["audio_cfg_scale"] = 4.0
    del wf["10"]
    del wf["12"]["inputs"]["lora"]
    wf["11"]["inputs"]["blocks_to_swap"] = 26
    wf["13"]["inputs"]["positive_prompt"] = EMOTION_PROMPT
    s = wf["15"]["inputs"]
    s.update({"steps": 20, "cfg": 5.0, "shift": 5.0, "scheduler": "unipc", "seed": 2})
    wf["17"]["inputs"]["filename_prefix"] = "lipservice/vowel_nolora"
    json.dump(wf, open(OUT, "w", encoding="utf8"), indent=2)
    print("wrote", OUT)


main()
