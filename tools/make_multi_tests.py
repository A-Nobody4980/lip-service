"""Build the two multi-singer tests on TownChoir1.png with the HearYeHearYe vocal.

Test 2: two singers (the man and the woman), the same vocal in both audio slots, one mask each.
Test 3: one audio slot and one mask over all three people.
Both use the baseline preset and the Multi model. Run from the project folder: python tools/make_multi_tests.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from app.masks import box_mask, orig_box_to_frame
from app.media import cut_audio_to_wav
from app.presets import BASELINE
from app.workflow import build_multi

SHOT, VOCAL = sys.argv[1], sys.argv[2]  # a picture with three people in it, and a vocal
INPUT = Path(r"D:\Comfy-Desktop\ComfyUI-Shared\input")
OUT = Path(__file__).resolve().parent.parent / "workflows"
START_S, FRAMES = 0.5, 81

# whole-person boxes in original pixels (1376 x 768)
MAN, WOMAN, YOUNG = (490, 170, 720, 768), (755, 255, 935, 768), (965, 230, 1150, 768)
ALL = (490, 170, 1150, 768)

PROMPT = ("three people in colonial market clothes stand in a muddy market square and sing together, "
          "mouths open, expressive faces, natural head and shoulder movement")


def main():
    img = Image.open(SHOT).convert("RGB")
    img.save(INPUT / "lipservice_choir1.png")
    dur = cut_audio_to_wav(VOCAL, str(INPUT / "lipservice_hearye_3s.wav"), START_S, START_S + FRAMES / 25)
    w, h = BASELINE.width, BASELINE.height
    names = {}
    for key, box in {"man": MAN, "woman": WOMAN, "all": ALL}.items():
        frac = orig_box_to_frame(box, img.size, w, h)
        name = f"lipservice_choir1_mask_{key}.png"
        box_mask(frac, w, h).save(INPUT / name)
        names[key] = name
    tests = {
        "multi_two_unison": (["lipservice_hearye_3s.wav"] * 2, [names["man"], names["woman"]]),
        "multi_group_one_slot": (["lipservice_hearye_3s.wav"], [names["all"]]),
    }
    for name, (audios, masks) in tests.items():
        wf = build_multi("lipservice_choir1.png", audios, masks, dur, f"lipservice/{name}", BASELINE, prompt=PROMPT)
        (OUT / f"{name}_api.json").write_text(json.dumps(wf, indent=2), encoding="utf8")
        print("wrote", name, "frames", wf["18"]["inputs"]["length"])


main()
