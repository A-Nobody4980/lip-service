import wave

import numpy as np
import pytest
from PIL import Image

from app.multi import mix_wavs, person_boxes, write_masks



def test_neighbour_boxes_do_not_overlap():
    boxes = person_boxes([{"x": .40, "y": .3, "r": .04}, {"x": .50, "y": .3, "r": .04}], 1000, 600)
    a, b = sorted(boxes)
    assert a[2] <= b[0] + 1e-6 and a[0] >= 0 and b[2] <= 1000 and a[3] == 600


def test_masks_written_and_rejected_outside_frame(tmp_path, sample_shot):
    names = write_masks([{"x": .5, "y": .3, "r": .06}], sample_shot, 832, 480, tmp_path, "t")
    m = Image.open(tmp_path / names[0])
    assert m.size == (832, 480) and m.getpixel((416, 400)) == (255, 255, 255) and m.getpixel((5, 5)) == (0, 0, 0)
    with pytest.raises(ValueError):
        write_masks([{"x": 0.001, "y": .3, "r": .0005}], sample_shot, 832, 480, tmp_path, "t")


def test_mix_adds_and_never_clips(tmp_path):
    def wav(path, level):
        with wave.open(str(path), "wb") as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(44100)
            w.writeframes((np.full(4410 * 2, level, dtype=np.int16)).tobytes())
    wav(tmp_path / "a.wav", 10000); wav(tmp_path / "b.wav", 10000)
    mix_wavs([tmp_path / "a.wav", tmp_path / "b.wav"], tmp_path / "m.wav")
    with wave.open(str(tmp_path / "m.wav")) as w:
        assert np.frombuffer(w.readframes(10), dtype=np.int16)[0] == 20000
    wav(tmp_path / "c.wav", 30000)
    mix_wavs([tmp_path / "c.wav", tmp_path / "c.wav"], tmp_path / "m2.wav")
    with wave.open(str(tmp_path / "m2.wav")) as w:
        assert np.abs(np.frombuffer(w.readframes(10), dtype=np.int16)).max() <= 32000


def test_background_mask_is_the_inverse_of_the_singers(tmp_path, sample_shot):
    from app.multi import write_masks
    names = write_masks([{"x": .45, "y": .3, "r": .04}, {"x": .55, "y": .3, "r": .04}], sample_shot, 832, 480, tmp_path, "t",
                        background=True)
    assert len(names) == 3 and names[-1].endswith("maskbg.png")
    a, b, bg = (Image.open(tmp_path / n).convert("L") for n in names)
    for x, y in [(5, 5), (416, 420), (100, 300), (700, 100), (416, 150)]:
        assert bg.getpixel((x, y)) == 255 - max(a.getpixel((x, y)), b.getpixel((x, y)))


def test_silence_has_the_right_length(tmp_path):
    from app.multi import make_silence
    p = make_silence(tmp_path / "s.wav", 2.0)
    with wave.open(str(p)) as w:
        assert w.getnframes() == 88200 and not any(w.readframes(100))


def test_build_multi_accepts_a_background_mask():
    from app.presets import BASELINE
    from app.workflow import build_multi
    wf = build_multi("a.png", ["v.wav", "silence.wav"], ["m0", "bg"], 3.0, "p", BASELINE)
    assert wf["8"]["inputs"]["audio_2"] == ["52", 0] and wf["40"]["inputs"] == {"masks.mask0": ["30", 0], "masks.mask1": ["31", 0]}
    wf = build_multi("a.png", ["v.wav", "v.wav"], ["m0", "m1", "bg"], 3.0, "p", BASELINE)
    assert list(wf["40"]["inputs"]) == ["masks.mask0", "masks.mask1", "masks.mask2"]
    with pytest.raises(ValueError):
        build_multi("a.png", ["v.wav"], ["m0", "m1", "m2"], 3.0, "p", BASELINE)
