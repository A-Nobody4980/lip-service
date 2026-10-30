import json
from pathlib import Path

from app.presets import BASELINE
from app.workflow import TEMPLATE, build_single

BASE = json.loads(Path(TEMPLATE).read_text(encoding="utf-8-sig"))


def test_baseline_values_unchanged():
    wf = build_single("lipservice_shot_01.webp", "lipservice_test_5s.wav", 5.0, "lipservice/x", BASELINE,
                      prompt=BASE["13"]["inputs"]["positive_prompt"],
                      negative_prompt=BASE["13"]["inputs"]["negative_prompt"])
    # Every node of the tested baseline is identical except the output node's prefix, images and audio.
    for node, spec in BASE.items():
        got = wf[node]
        if node == "17":
            expected = dict(spec["inputs"])
            expected.pop("audio")
            expected["images"] = ["18", 0]
            expected["filename_prefix"] = "lipservice/x"
            assert got["inputs"] == expected
        else:
            assert got == spec, node
    assert wf["18"]["inputs"]["length"] == 125


def test_isolation_toggle():
    off = build_single("a.png", "b.wav", 3.0, "p", BASELINE)
    on = build_single("a.png", "b.wav", 3.0, "p", BASELINE, isolate_vocals=True)
    assert "21" not in off and off["8"]["inputs"]["audio_1"] == ["6", 0]
    assert on["8"]["inputs"]["audio_1"] == ["21", 0]
    assert on["21"]["inputs"]["audio"] == ["6", 0]


def test_multi_unison_two_singers():
    from app.workflow import build_multi
    wf = build_multi("a.png", ["v.wav", "v.wav"], ["m0.png", "m1.png"], 3.24, "p", BASELINE)
    emb = wf["8"]["inputs"]
    assert emb["audio_1"] == emb["audio_2"] == ["6", 0]          # same vocal in both slots
    assert emb["ref_target_masks"] == ["40", 0]
    assert wf["40"]["inputs"] == {"masks.mask0": ["30", 0], "masks.mask1": ["31", 0]}
    assert wf["9"]["inputs"]["model"].endswith("Multi_Q8.gguf")
    assert wf["15"]["inputs"]["steps"] == 6 and wf["11"]["inputs"]["blocks_to_swap"] == 20


def test_multi_group_one_slot_and_limits():
    import pytest
    from app.workflow import build_multi
    wf = build_multi("a.png", ["v.wav"], ["group.png"], 3.0, "p", BASELINE)
    assert "audio_2" not in wf["8"]["inputs"]
    with pytest.raises(ValueError):
        build_multi("a.png", ["v.wav"] * 5, ["m"] * 5, 3.0, "p", BASELINE)


def test_multi_isolation_runs_per_distinct_audio():
    from app.workflow import build_multi
    wf = build_multi("a.png", ["v1.wav", "v2.wav"], ["m0", "m1"], 3.0, "p", BASELINE, isolate_vocals=True)
    emb = wf["8"]["inputs"]
    assert emb["audio_1"] == ["21", 0] and emb["audio_2"] == ["62", 0]
    assert wf["62"]["inputs"]["audio"] == ["52", 0]
