"""Run one Lip Service job through the Comfy SDK and comfy-api-proxy (local only)."""
import os
import shutil
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from dataclasses import replace

from .media import audio_duration, cut_audio_to_wav, mux_original_audio
from .multi import cut_singer_audios, make_silence, mix_wavs, write_masks
from . import hardware
from .presets import ASPECTS, BEST_MODEL, Preset, get_preset
from .workflow import DEFAULT_NEGATIVE, DEFAULT_PROMPT, MAX_SINGERS, build_multi, build_single

PROXY_URL = os.environ.get("LIPSERVICE_PROXY_URL", "http://127.0.0.1:8189")
COMFY_ROOT = Path(os.environ.get("LIPSERVICE_COMFY_SHARED", r"D:\Comfy-Desktop\ComfyUI-Shared"))
COMFY_INPUT = COMFY_ROOT / "input"
COMFY_OUTPUT = COMFY_ROOT / "output"
PROJECT = Path(__file__).resolve().parent.parent
OUTPUTS = PROJECT / "outputs"
JOBS_DIR = OUTPUTS / "jobs"


@dataclass
class JobSpec:
    job_id: str
    shot: str
    audio: str
    prompt: str = DEFAULT_PROMPT
    negative_prompt: str = DEFAULT_NEGATIVE
    audio_start: float = 0.0
    audio_end: float | None = None
    isolate_vocals: bool = False
    preset: Preset = field(default_factory=get_preset)
    aspect: str = "16:9"
    model: str | None = None
    singers: list = field(default_factory=list)       # [{"x","y","r"}] fractions of the image, empty = one singer
    unison: bool = True
    singer_audios: list = field(default_factory=list)
    quality: float = 0.38
    seconds: float = 0.0                              # selection length, for the queue list only
    sing_along: bool = False                          # True: unmarked people also sing (the free choir mode)


def settings_for(spec, vram=None, size_of=None, pixels=hardware.REF_PIXELS):
    """The base model and the block swap for a job. Best always uses the Q6_K base; the other positions use the
    model that was picked. The block swap follows the file size and the card's memory."""
    model = BEST_MODEL if spec.preset.name == "best" else spec.model
    path = COMFY_ROOT / "models" / "diffusion_models" / (model or r"WanVideo\wan2.1-i2v-14b-480p-Q4_K_M.gguf")
    try:
        size = size_of(path) if size_of else path.stat().st_size
    except OSError:
        return model, spec.preset.blocks_to_swap
    return model, hardware.blocks_to_swap(size, vram, pixels)


def _local_only(url: str) -> None:
    host = urllib.parse.urlparse(url).hostname
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise RuntimeError(f"Lip Service only talks to a local proxy, got {url}")


def _client():
    from comfy_sdk import Comfy

    _local_only(PROXY_URL)
    os.environ["COMFY_BASE_URL"] = PROXY_URL
    return Comfy(timeout=120)


def wait_for_job(job, log=print, limit_s=4 * 3600, max_errors=60):
    """Waits until the render ends. A slow or dropped answer from the proxy while ComfyUI is busy is not a
    failure: keep asking. Only a long run of errors, or the time limit, gives up."""
    import httpx

    end = time.time() + limit_s
    errors = 0
    while time.time() < end:
        try:
            job.wait(timeout=30)
            return job
        except TimeoutError:
            errors = 0  # the job is just still running
        except (httpx.TimeoutException, httpx.TransportError) as e:
            errors += 1
            if errors > max_errors:
                raise
            log(f"no answer from the proxy ({type(e).__name__}), asking again")
            time.sleep(5)
    raise TimeoutError("the render took longer than the time limit")


def _find_video(job_id: str, started: float) -> Path:
    """Newest mp4 the render wrote under output/lipservice for this job."""
    folder = COMFY_OUTPUT / "lipservice"
    hits = [p for p in folder.glob(f"{job_id}*.mp4") if p.stat().st_mtime >= started - 5]
    if not hits:
        raise RuntimeError(f"render finished but no video named {job_id}*.mp4 in {folder}")
    return max(hits, key=lambda p: p.stat().st_mtime)


def run_job(spec: JobSpec, log=print) -> Path:
    """Returns the path of the finished shot with the original audio muxed on."""
    work = JOBS_DIR / spec.job_id
    work.mkdir(parents=True, exist_ok=True)
    multi = bool(spec.singers)
    if multi and not spec.unison and len(spec.singer_audios) != len(spec.singers):
        raise ValueError("Give one audio track for each marked singer.")

    # 1. The audio for this shot. This is the original audio and it goes back on at the end.
    seg = work / "original_audio.wav"
    if multi and not spec.unison:
        files, duration = cut_singer_audios(spec.singer_audios, spec.audio_start, spec.audio_end, work)
        mix_wavs(files, seg)  # the sound on the finished shot is every singer's track together
    else:
        files = [seg] * (len(spec.singers) if multi else 1)
        duration = cut_audio_to_wav(spec.audio, str(seg), spec.audio_start, spec.audio_end)
    if duration < 0.5:
        raise ValueError("audio segment is shorter than half a second")
    log(f"audio segment: {duration:.2f} s")

    # Only marked singers sing, unless sing_along is on. A background mask alone does not mute anyone (test of
    # Oct 29: the unmarked man still sang), so everyone unmarked is given to an extra slot that plays silence.
    # That slot needs room: with 4 singers marked there is none, and only the background mask is used.
    quiet = multi and not spec.sing_along
    slots = list(files)
    if quiet and len(spec.singers) < MAX_SINGERS:
        silence = work / "silence.wav"
        make_silence(silence, duration)
        slots.append(silence)

    # 2. Copy inputs where ComfyUI reads them.
    shot_name = f"lipservice_{spec.job_id}_shot{Path(spec.shot).suffix.lower()}"
    COMFY_INPUT.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(spec.shot, COMFY_INPUT / shot_name)
    audio_names = []
    for i, f in enumerate(dict.fromkeys(slots)):  # one copy per distinct file, so unison shares one slot source
        name = f"lipservice_{spec.job_id}_audio{i + 1}.wav"
        shutil.copyfile(f, COMFY_INPUT / name)
        audio_names.append((f, name))
    name_of = dict(audio_names)

    # 3. Build and submit.
    size = ASPECTS[spec.aspect]
    model, swap = settings_for(spec, hardware.vram_mib(), pixels=size["width"] * size["height"])
    preset = replace(spec.preset, width=size["width"], height=size["height"], blocks_to_swap=swap)
    log(f"quality {spec.preset.name}: {preset.steps} steps, block swap {swap}")
    ram = hardware.ram_status()  # a notice only: a low value never stops a render
    if not ram["ram_ok"]:
        log(f"low memory notice: {ram['ram_free_gb']} GB free, a render peaks near {ram['ram_needed_gb'] + 4} GB")
    prefix = f"lipservice/{spec.job_id}"
    if multi:
        masks = write_masks(spec.singers, spec.shot, size["width"], size["height"], COMFY_INPUT,
                            f"lipservice_{spec.job_id}", background=quiet)
        graph = build_multi(shot_name, [name_of[f] for f in slots], masks, duration, prefix, preset,
                            spec.prompt, spec.negative_prompt, spec.isolate_vocals, model=model)
        log(f"{len(spec.singers)} singers, {'same vocal' if spec.unison else 'separate tracks'}, "
            f"{'unmarked people sing along' if spec.sing_along else 'only marked singers sing'}")
    else:
        graph = build_single(shot_name, name_of[files[0]], duration, prefix, preset,
                             spec.prompt, spec.negative_prompt, spec.isolate_vocals, model=model)
    client = _client()
    started = time.time()
    job = client.submit(client.workflows.from_json(graph))
    log(f"submitted {job.id}")
    wait_for_job(job, log)
    job = job.result()
    log(f"render status: {job.status} after {time.time() - started:.0f} s")
    if str(job.status).lower() != "succeeded":
        raise RuntimeError(f"render did not finish: {job.status} {getattr(job, 'error', '')}")

    # 4. Mux the original audio onto the cut video.
    video = _find_video(spec.job_id, started)
    final = OUTPUTS / f"{spec.job_id}.mp4"
    mux_original_audio(str(video), str(seg), str(final))
    log(f"done: {final}")
    return final
