import threading
import time
from types import SimpleNamespace

import pytest

from app import hardware, server
from app.presets import BASELINE, BEST, BEST_MODEL, FAST, PRESETS, quality_id
from app.queue import JobQueue
from app.runner import settings_for

Q4_BYTES, Q6_BYTES = 11_341_200_000, 14_233_779_584


def test_default_preset_is_untouched_and_fast_only_changes_steps():
    assert PRESETS["baseline"] is BASELINE and BASELINE.steps == 6 and BASELINE.shift == 11.0
    assert BASELINE.blocks_to_swap == 20
    assert FAST == BASELINE.__class__(**{**BASELINE.__dict__, "name": "fast", "steps": 4})
    assert BEST.steps == 6 and BEST.shift == 11.0 and BEST.cfg == 1.0 and BEST.scheduler == BASELINE.scheduler


def test_quality_snaps_to_the_nearest_position():
    assert [quality_id(v) for v in (0, 0.2, 0.3, 0.5, 0.7, 0.8, 1, None)] == \
        ["fast", "fast", "default", "default", "default", "best", "best", "default"]


def test_block_swap_follows_model_size_and_card_memory():
    assert hardware.blocks_to_swap(Q4_BYTES, 12227) == 20      # the tested default on the RTX 5070
    assert hardware.blocks_to_swap(Q4_BYTES, None) == 20       # unknown card: be careful
    assert hardware.blocks_to_swap(Q4_BYTES, 12288) == 20      # another 12 GB card
    assert hardware.blocks_to_swap(Q6_BYTES, 12227) == 25      # Best on the 12 GB card swaps more
    assert hardware.blocks_to_swap(Q4_BYTES, 16384) < 20 and hardware.blocks_to_swap(Q6_BYTES, 16384) < 25
    assert hardware.blocks_to_swap(Q4_BYTES, 24576) == 0       # a big card keeps it all
    assert hardware.blocks_to_swap(Q6_BYTES, 24576) == 0


def test_vram_reading_survives_a_missing_nvidia_smi(monkeypatch):
    monkeypatch.setattr(hardware.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    assert hardware.vram_mib() is None


def spec(preset, model="WanVideo/x.gguf"):
    return SimpleNamespace(preset=preset, model=model)


def test_settings_for_best_uses_q6_and_default_keeps_the_picked_model():
    sizes = {BEST_MODEL.split("\\")[-1]: Q6_BYTES, "x.gguf": Q4_BYTES}
    size_of = lambda p: sizes[p.name]
    assert settings_for(spec(BEST), 12227, size_of) == (BEST_MODEL, 25)
    assert settings_for(spec(BASELINE), 12227, size_of) == ("WanVideo/x.gguf", 20)
    assert settings_for(spec(FAST), 12227, size_of) == ("WanVideo/x.gguf", 20)
    assert settings_for(spec(BASELINE), 24576, size_of) == ("WanVideo/x.gguf", 0)


class FakeMgr:
    def is_up(self): return True
    def ensure_up(self): pass
    def restart(self): pass


@pytest.fixture()
def api(tmp_path, monkeypatch):
    root = tmp_path / "models"
    models = root / "WanVideo"
    models.mkdir(parents=True)
    (models / "wan2.1-i2v-14b-480p-Q4_K_M.gguf").write_bytes(b"x")
    monkeypatch.setattr(server, "MODELS_DIR", root)
    q = JobQueue(run_fn=lambda s, log: "x.mp4", state_file=tmp_path / "q.json")
    return server.Api(q, FakeMgr(), FakeMgr(), "t"), models, q


def job_body(sample_shot, sample_wav, **extra):
    return {"shot": sample_shot, "audio": sample_wav, "start": 1, "end": 4, **extra}


def test_options_lists_three_positions_and_disables_best_without_the_file(api):
    a, models, _ = api
    pos = {p["id"]: p for p in a.options()["quality"]["positions"]}
    assert list(pos) == ["fast", "default", "best"] and a.options()["quality"]["default"] == 0.5
    assert pos["fast"]["enabled"] and pos["default"]["enabled"] and not pos["best"]["enabled"] and pos["best"]["note"]
    (models / "wan2.1-i2v-14b-480p-Q6_K.gguf").write_bytes(b"x")
    assert {p["id"]: p for p in a.options()["quality"]["positions"]}["best"]["enabled"]


def test_job_quality_picks_the_preset(api, sample_shot, sample_wav):
    a, models, q = api
    (models / "wan2.1-i2v-14b-480p-Q6_K.gguf").write_bytes(b"x")
    ids = {name: a.add_job(job_body(sample_shot, sample_wav, quality=v))["id"] for name, v in
           (("fast", 0), ("default", 0.5), ("best", 1))}
    presets = {j["id"]: j["preset"] for j in q.snapshot()}
    assert [presets[ids[n]] for n in ("fast", "default", "best")] == ["fast", "baseline", "best"]


def test_best_is_refused_when_the_q6_file_is_missing(api, sample_shot, sample_wav):
    a, _, _ = api
    with pytest.raises(server.ApiError) as e:
        a.add_job(job_body(sample_shot, sample_wav, quality=1))
    assert e.value.status == 400


def test_status_reports_memory_and_the_warning_flag(api, monkeypatch):
    a, _, _ = api
    s = a.status()
    assert {"ram_free_gb", "ram_needed_gb", "ram_ok"} <= set(s)
    monkeypatch.setattr(hardware.psutil, "virtual_memory", lambda: SimpleNamespace(available=8e9))
    s = a.status()
    assert s["ram_free_gb"] == 8.0 and s["ram_ok"] is False and s["ram_needed_gb"] == 22
    monkeypatch.setattr(hardware.psutil, "virtual_memory", lambda: SimpleNamespace(available=25e9))
    assert a.status()["ram_ok"] is True


def test_bigger_frames_swap_one_more_block_and_smaller_ones_do_not():
    from app.presets import ASPECTS
    px = {k: v["width"] * v["height"] for k, v in ASPECTS.items()}
    assert hardware.blocks_to_swap(Q4_BYTES, 12227, px["16:9"]) == 20     # the tested size, unchanged
    assert hardware.blocks_to_swap(Q4_BYTES, 12227, px["9:16"]) == 20     # same pixel count, turned
    assert hardware.blocks_to_swap(Q4_BYTES, 12227, px["4:3"]) == 20      # fewer pixels
    assert hardware.blocks_to_swap(Q4_BYTES, 12227, px["1:1"]) == 21      # 2.6 percent more pixels
    assert hardware.blocks_to_swap(Q6_BYTES, 12227, px["1:1"]) == 26
    assert hardware.blocks_to_swap(Q4_BYTES, 24576, px["1:1"]) == 0       # a big card still keeps it all
    assert all(w % 16 == 0 and h % 16 == 0 for w, h in ((v["width"], v["height"]) for v in ASPECTS.values()))


def test_model_list_reads_every_folder_and_skips_the_infinitetalk_weights(api):
    a, wan, _ = api
    root = wan.parent
    (wan / "InfiniteTalk").mkdir()
    (wan / "InfiniteTalk" / "Wan2_1-InfiniteTalk_Single_Q8.gguf").write_bytes(b"x")
    (root / "MelBandRoFormer").mkdir()
    (root / "MelBandRoFormer" / "m.gguf").write_bytes(b"x")
    (wan / "wan2.1-t2v-14b-Q4_K_M.gguf").write_bytes(b"x")
    (root / "mine").mkdir()
    (root / "mine" / "my-i2v.gguf").write_bytes(b"x")
    ids = [m["id"] for m in a.options()["models"]]
    assert sorted(ids) == ["WanVideo\\wan2.1-i2v-14b-480p-Q4_K_M.gguf", "mine\\my-i2v.gguf"]
