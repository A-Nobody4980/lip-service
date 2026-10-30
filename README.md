# Lip Service

Open Source Higgsfield Lipsync Studio, built for singers.

Lip Service is a performance director for cinematic and music video shots. You give it one still shot of your character and an audio track. The character sings or speaks it, with mouth, head, body and expression driven by the voice, and you get the finished shot back with your original audio on it. It runs on your own PC, on open weight models, with no cloud and no credits. It was built and tested on a 12 GB RTX 5070.

It works shot by shot, so you stay in control of every take. It supports one singer, several singers in one shot, and a group singing the same part.

## What you can do

1. Drop in an image and an audio file (your vocal, someone else's, dialogue, or a full song mix). You can also click a box to choose a file.
2. Pick the part you want on a waveform. Click to set the start and end, or type the times. Play the selection to check it.
3. Write the emotion and action in the prompt box.
4. Choose Single or Multiple singers. For Multiple, click each face on the image, then choose one vocal for everyone (unison) or a separate track for each singer. Only the people you mark sing. Switch on "Unmarked people sing along" if you want everyone in the picture to join in, a free choir.
5. Turn on "Isolate the vocal" if your audio is a full mix or noisy. It is off by default.
6. Pick a quality with the slider: Fast draft, Default or Best, and an aspect ratio: 16:9, 9:16, 1:1 or 4:3.
7. Press Render shot. Jobs go into a queue. Finished shots are saved to the `outputs` folder with the original audio on.

## How it works

- The screen is a desktop window built with Electron. It talks only to a small Python backend on `127.0.0.1`, protected by a random token.
- The backend builds a ComfyUI workflow and runs it through the Comfy SDK and the local `comfy-api-proxy`.
- The model is InfiniteTalk (MeiGen) on Wan 2.1 image to video 14B, in GGUF form with the lightx2v speed LoRA, so it fits in 12 GB.
- ComfyUI is restarted after every render so memory never piles up between jobs.
- The finished video is trimmed to the audio length and your original audio is muxed back on.

## What to expect

### Quality and time

Measured on an RTX 5070 (12 GB), one 3.24 s clip per mode, including loading the models:

| Quality | What it is | Time | GPU memory peak (card has 12,227 MiB) |
|---|---|---|---|
| Fast draft | The Default look with 4 steps instead of 6 | 510 s (8.5 min) | 11,796 MiB |
| Default | The look the project is tuned on: Wan 2.1 Q4_K_M base, 6 steps, lightx2v LoRA, block swap 20 | 616 to 787 s (10 to 13 min), from earlier runs that varied with other programs running | 11,852 MiB |
| Best | The same settings as Default, but with the larger Q6_K base file and a block swap of 25 | 970 s (16.2 min) | 11,785 MiB |

A 12 s shot at Default took about 31 minutes. Best has slightly finer detail in the eyes, hair and skin in the one comparison made. The slider snaps to three positions. Max (a 720p mode) is not built. The block swap is set from your card's memory: bigger cards swap less, and on the 12 GB test card Default and Fast use exactly 20.

Memory: a render peaks near 26 GB of PC memory in every quality position, so a 32 GB PC with a large page file is the minimum. When less than 22 GB is free the screen shows a notice. It never stops a render.

### Aspect ratios and cropping

- Four aspect ratios work, each at about 400,000 pixels: 16:9 (832x480), 9:16 (480x832), 1:1 (640x640) and 4:3 (704x528). Each was test-rendered at Fast quality for 3.24 s on the 12 GB card and finished: 9:16 in 465 s, 1:1 in 490 s and 4:3 in 430 s, with a peak of about 11.8 GB of GPU memory. The 1:1 size uses one more block of swap than the others. The model officially lists only 16:9 and 9:16, so judge the 1:1 and 4:3 faces on your own shots.
- The image is center-cropped to the chosen aspect ratio, and the app shows no preview of that crop. Anything outside the crop is lost, so frame your singers near the middle of the picture. A landscape photo turned into 9:16 keeps only a narrow strip down the middle.

### Singers and audio

- Up to 4 singers per shot. To keep the unmarked people quiet, the app gives everyone you did not mark to a silent audio track, which uses one of the 4 audio slots. So quiet mode works with up to 3 marked singers. With 4 marked singers the unmarked people are only masked out, which is weak.
- With one audio slot the model ignores the masks, so the app always uses extra slots to tell singers apart.
- "Isolate the vocal" was tested on a real full song mix against the song's own lead vocal stem. Lined up in time, the isolated vocal matched the stem at 0.90 (the raw mix matched at 0.83), and the other output held none of the lead vocal (-0.01). So it works, but the gain is modest when the lead is already loud in the mix. The render with it on took 616 s for 3.24 s, in line with the other renders.
- The window warns you when the selection is longer than a tested length. The longest single shot tested is 12 s.

## Known weak spots

- **Held vowels.** On a long held note the mouth stays a round, open "ah" or "oh" shape instead of the vowel actually sung. In a test on a held "sake", changing the audio strength and the audio guidance changed the energy and emotion of the performance, not the vowel shape.
- **Consonant mouth shapes.** Lip closure for sounds like M, B and P, and the difference between M (lips closed) and N (lips apart), have not been measured. The model does not promise exact mouth shapes for each sound, so expect looser shapes than a dedicated viseme tool. Fast speech and rap with sudden pauses have not been tested either.
- **Faces in wide shots.** When a face is small in the frame it can drift away from the original within the first half second and does not come back. Frame the shot closer, or crop in before you drop it in. A face about 200 px wide in the frame held much better than one about 94 px wide.
- **Not yet test-rendered.** A separate track for each singer, the "Unmarked people sing along" switch turned on, and shots with 3 or 4 marked singers are built and covered by automated tests, but no real render has been judged for them yet.
- Lip sync was judged by eye on short clips, not measured.

## Setup (Windows)

You need an NVIDIA card with 12 GB or more, the current NVIDIA driver, 32 GB of RAM and a large page file.

1. Install ComfyUI and put these custom nodes in it: [kijai/ComfyUI-WanVideoWrapper](https://github.com/kijai/ComfyUI-WanVideoWrapper), [Kosinkadink/ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite), and optionally [kijai/ComfyUI-MelBandRoFormer](https://github.com/kijai/ComfyUI-MelBandRoFormer) for vocal isolation.
2. Download the models into your ComfyUI models folders. Nothing is bundled here. The folders below are relative to the ComfyUI `models` folder, except the audio encoder, which the wrapper reads from `ComfyUI\models\wav2vec2` inside the ComfyUI install.

| File | Size | Download | Put it in |
|---|---|---|---|
| `wan2.1-i2v-14b-480p-Q4_K_M.gguf` | 11.3 GB | [city96/Wan2.1-I2V-14B-480P-gguf](https://huggingface.co/city96/Wan2.1-I2V-14B-480P-gguf) | `diffusion_models\WanVideo` |
| `wan2.1-i2v-14b-480p-Q6_K.gguf` (only for Best) | 14.2 GB | same page | `diffusion_models\WanVideo` |
| `Wan2_1-InfiniteTalk_Single_Q8.gguf` and `Wan2_1-InfiniteTalk_Multi_Q8.gguf` | 2.6 GB each | [Kijai/WanVideo_comfy_GGUF](https://huggingface.co/Kijai/WanVideo_comfy_GGUF) (in its `InfiniteTalk` folder) | `diffusion_models\WanVideo\InfiniteTalk` |
| `umt5-xxl-enc-bf16.safetensors` | 11.4 GB | [Kijai/WanVideo_comfy](https://huggingface.co/Kijai/WanVideo_comfy) | `text_encoders` |
| `lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors` | 0.74 GB | same page (in its `Lightx2v` folder) | `loras\WanVideo\Lightx2v` |
| `Wan2_1_VAE_bf16.safetensors` | 0.25 GB | same page | `vae` |
| `clip_vision_h.safetensors` | 1.3 GB | [Comfy-Org/Wan_2.1_ComfyUI_repackaged](https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged) (in `split_files\clip_vision`) | `clip_vision` |
| `wav2vec2-chinese-base_fp16.safetensors` | 0.19 GB | [Kijai/wav2vec2_safetensors](https://huggingface.co/Kijai/wav2vec2_safetensors) | `ComfyUI\models\wav2vec2` |
| `MelBandRoformer_fp16.safetensors` (optional, vocal isolation) | 0.46 GB | [Kijai/MelBandRoFormer_comfy](https://huggingface.co/Kijai/MelBandRoFormer_comfy) | `diffusion_models\MelBandRoFormer` |

3. Create the Python environment: `python -m venv .venv`, then `.venv\Scripts\pip install -r requirements.txt`.
4. Install the window: `cd desktop`, then `npm install`. Node.js is needed for this step only.
5. Tell the app where ComfyUI is. The defaults are `D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI` and `D:\Comfy-Desktop\ComfyUI-Shared`. Set these environment variables if yours are elsewhere: `LIPSERVICE_COMFY_HOME` (the ComfyUI install folder that holds `ComfyUI\.venv`), `LIPSERVICE_COMFY_SHARED` (the folder with `input`, `output` and `models`), and `LIPSERVICE_COMFY_MODEL_PATHS` (an extra model paths file, or empty for none; the app finds Comfy Desktop's own file by itself).
6. Make the shortcuts: `powershell -ExecutionPolicy Bypass -File launch\create-shortcuts.ps1`. It always adds a Lip Service shortcut to your Start menu, then asks "Add a desktop shortcut too? (Y/N)" and adds one to your Desktop only if you answer Y. It uses the Desktop folder Windows reports, so it works whether or not your Desktop is kept in OneDrive. Add `-DryRun` to see what it would do without creating anything.
7. Start the app from the shortcut, or with `launch\start-lip-service.ps1`. It starts the backend and the window. ComfyUI and the proxy start by themselves when a render needs them.

## Examples

Real outputs from a 12 GB RTX 5070, in `examples`. The character and the vocals are the project owner's own.

- `single-singer-3s.mp4`: one singer, 3.2 s, rendered through the app.
- `single-singer-12s.mp4`: one singer, 12 s, five windows in one job.
- `closer-crop-3s.mp4`: the same singer framed closer, which keeps her face.
- `two-singers-unmarked-quiet-3s.mp4`: two marked singers on one vocal. The third person in the picture stays quiet.

## Tests

`.venv\Scripts\python -m pytest tests` runs the tests. They need no GPU, no ComfyUI and no models: they make their own sample audio, pictures and video. The screen has its own test, `desktop\node_modules\electron\dist\electron.exe . --smoke`, which runs against a mock backend in a hidden window.

## Project layout

- `app/` is the Python backend: the workflow builder, the queue, the ComfyUI and proxy starters, the local API (`docs/api.md`).
- `desktop/` is the Electron window. `desktop/dev/` holds a mock backend and the smoke test.
- `launch/` holds the launcher, the shortcut maker and the icon.
- `workflows/` holds the ComfyUI workflow files (API format). `tools/` holds test and helper scripts.

## Privacy

Lip Service sends nothing anywhere. The window only talks to `127.0.0.1`, spellcheck, crash reporting and updates are off, and Chromium's background networking is disabled. We watched the blank window for 75 seconds and saw no network connections. Start ComfyUI without its telemetry flag (the app does this when it starts ComfyUI for you). Everything the app writes stays inside the project folder.

## Licenses

All components are used under their own licenses. Models are not bundled: download them from the links above. Check each license yourself before commercial use. Rows marked UNCONFIRMED have not been fully checked.

| Component | License | Notes |
|---|---|---|
| InfiniteTalk weights (MeiGen) | Apache 2.0 | No rights claimed over outputs |
| Wan 2.1 I2V 14B (Wan-AI) and the GGUF files by city96 (Q4_K_M, Q6_K) | Apache 2.0 | |
| lightx2v speed LoRA | Apache 2.0 upstream | Stated on the lightx2v model card. The Kijai copy we use has no license tag of its own. |
| umt5-xxl text encoder (Kijai copy, encoder only, bf16) | UNCONFIRMED | The original google/umt5-xxl is tagged Apache 2.0 on Hugging Face, but its license text was not opened. The Kijai repository states no license. |
| Wan 2.1 VAE (Kijai copy) | Apache 2.0 upstream | The Kijai repository states no license |
| clip_vision_h (Comfy-Org repackaged) | Apache 2.0 | Tagged on the repository |
| chinese-wav2vec2-base, Kijai fp16 copy | MIT | |
| kijai ComfyUI-WanVideoWrapper | Apache 2.0 | No telemetry |
| kijai ComfyUI-MelBandRoFormer (optional) | No license file in the repo | Linked, not copied. Weights are tagged MIT upstream, training data is not documented. The Kijai weights repository states no license. |
| Kosinkadink ComfyUI-VideoHelperSuite | GPL 3.0 | Used as a ComfyUI node at runtime, not copied into this repo |
| comfy-sdk, comfy-api-proxy | MIT | Local only |
| Electron | MIT | License files shipped in `desktop/licenses` |
| Chromium (inside Electron) | BSD and others | `desktop/licenses/LICENSES.chromium.html` |
| Node.js (setup only) | MIT | |
| PyAV | BSD 3-Clause | The FFmpeg inside its pip wheel is UNCONFIRMED: PyAV does not state that build's license, and the build includes the x264 and x265 encoders, which are GPL libraries, so treat it as a GPL build. Lip Service only copies the video stream and uses FFmpeg's built-in AAC encoder, and it does not ship PyAV: pip installs it. |
| numpy, Pillow, psutil, httpx | BSD, HPND, BSD, BSD | |
| Not used | | Demucs weights (research only), LatentSync and Wav2Lip (non-commercial), MiniMax H3 (paid license) |

## License

Lip Service is released under the MIT License (see `LICENSE`). Copyright (c) 2026 A. Nobody JLN. The models and nodes it uses keep their own licenses, listed above.
