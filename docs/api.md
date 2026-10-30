# Lip Service local API (screen to backend)

The Electron screen talks to a small Python backend on this PC. Nothing here ever leaves the machine.

- Base URL: `http://127.0.0.1:8780`. Bound to 127.0.0.1 only.
- Every request must send the header `X-Lip-Token: <token>`. The token comes from the environment variable `LIPSERVICE_TOKEN`, which both the backend and Electron are started with. Missing or wrong token: HTTP 401 `{"error": "bad token"}`.
- CORS: the page runs from `file://` (origin `null`). The backend answers `Access-Control-Allow-Origin: null`, allows the headers `X-Lip-Token, Content-Type`, and handles `OPTIONS`.
- JSON in, JSON out, UTF-8. Errors are `{"error": "plain words"}` with a 4xx or 5xx status.
- All file paths are absolute Windows paths as strings, for example `D:\\Photos\\shot.png`. Electron gives them to the page with `webUtils.getPathForFile(file)`, so no file is ever uploaded.
- Times are seconds as numbers. Fractions are 0 to 1.

## Endpoints

### GET /ping
`{"ok": true}` at once. Used by the launcher to know the backend is up. It needs the token like every other call.

### GET /status
```json
{"comfyui": true, "proxy": true, "restarting": false, "busy": false,
 "ram_free_gb": 21.3, "ram_needed_gb": 22, "ram_ok": false}
```
`ram_free_gb` is the free memory in the PC right now. A render peaks near 26 GB of memory in every quality position, so the PC should start with about `ram_needed_gb` free. When `ram_ok` is false the screen shows a NOTICE (for every quality position, not only Best). It never blocks or changes the render.
The values are refreshed in the background every 3 seconds, so the answer is instant but can be a few seconds old. `comfyui` true means the status light is cyan and says "ComfyUI connected". `restarting` true means "Restarting ComfyUI". `busy` true means a job is running.

### GET /options
```json
{
  "models": [{"id": "WanVideo\\wan2.1-i2v-14b-480p-Q4_K_M.gguf", "label": "Wan 2.1 I2V 14B 480p Q4_K_M", "default": true}],
  "aspects": [
    {"id": "16:9", "label": "16:9", "width": 832, "height": 480, "enabled": true, "default": true},
    {"id": "9:16", "label": "9:16", "width": 480, "height": 832, "enabled": true},
    {"id": "1:1",  "label": "1:1",  "width": 640, "height": 640, "enabled": true},
    {"id": "4:3",  "label": "4:3",  "width": 704, "height": 528, "enabled": true}
  ],
  "quality": {"default": 0.5, "enabled": true, "positions": [
    {"id": "fast", "value": 0.0, "label": "Fast draft", "enabled": true},
    {"id": "default", "value": 0.5, "label": "Default", "enabled": true},
    {"id": "best", "value": 1.0, "label": "Best", "enabled": true}
  ]},
  "limits": {"warn_seconds": 12},
  "max_singers": 4
}
```
The quality slider has exactly three snap positions, taken from `quality.positions` (left to right: Fast draft 0, Default 0.5, Best 1). A position with `enabled` false (Best when the Q6_K file is missing) is dimmed with its `note` as a tooltip and cannot be chosen. The screen sends `quality` as the chosen position's `value`. The screen builds the model picker and aspect ratio buttons from this. The backend only lists aspect ratios that work on the test card, so every aspect button is live. Any item that did have `enabled` false would be shown dimmed with the `note` as a tooltip and cannot be chosen. The quality slider sits at `default` and is not draggable while `enabled` is false.

### POST /audio/info
Request: `{"path": "D:\\audio\\song.wav"}`
Response: `{"duration": 6.0, "peaks": [0.0, 0.1, 0.4]}` where `peaks` is 500 numbers from 0 to 1, one per equal slice of the file, for drawing the waveform.

### GET /audio/segment?path=...&start=0.5&end=5.1
Returns `audio/wav` of that part, for the Play selection button. The page fetches it with the token header and plays it from a blob URL.

### POST /jobs
Request:
```json
{
  "shot": "D:\\pics\\witch.png",
  "audio": "D:\\audio\\song.wav",
  "start": 0.5,
  "end": 5.1,
  "prompt": "a woman sings with raw emotion",
  "negative_prompt": "",
  "isolate_vocals": false,
  "singers": [],
  "unison": true,
  "singer_audios": [],
  "sing_along": false,
  "quality": 0.5,
  "aspect": "16:9",
  "model": "WanVideo\\wan2.1-i2v-14b-480p-Q4_K_M.gguf"
}
```
- `end` 0 means to the end of the file. An empty `negative_prompt` means "use the default".
- `singers`: empty for a single singer. For several singers, one entry per marked face: `{"x": 0.45, "y": 0.30, "r": 0.045}` where x and y are the ring centre as a fraction of the shown image width and height, and r is the ring radius as a fraction of the image width. Up to `max_singers`.
- `unison` true: the one `audio` selection is used for every singer. false: `singer_audios` holds one absolute path per singer, in the same order, and each uses the same `start` and `end`.
- `sing_along` (default false): false means only the marked singers sing and everyone else in the picture stays quiet. true means unmarked people sing along with the nearest singer (the free choir mode). Only used when `singers` is not empty.
- Response: `{"id": "20261029-101500-ab12"}`. Bad input: HTTP 400 with a plain error.

### GET /jobs
```json
{"jobs": [{"id": "20261029-101500-ab12", "status": "running", "added": 1793000000.0, "shot": "D:\\pics\\witch.png",
           "audio": "D:\\audio\\song.wav", "seconds": 4.6, "note": "restarting ComfyUI to free memory",
           "result": null, "elapsed": 312.0}]}
```
`status` is one of `queued`, `running`, `done`, `failed`, `cancelled`. Newest first. `note` is the last log line, or the error when failed. `result` is the absolute path of the finished mp4 when done.

### POST /jobs/{id}/remove
Takes one row out of the queue list: `{"ok": true}`. Works for `queued` (it is cancelled and removed), `done`, `failed` and `cancelled` rows. A `running` row cannot be removed: HTTP 409. Only the row goes, the finished video file is never deleted.

### POST /jobs/clear
Removes every `done`, `failed` and `cancelled` row at once and returns `{"removed": 3}`. `queued` and `running` rows are never touched.

### POST /jobs/{id}/cancel
`{"ok": true}`. Only queued jobs can be cancelled; otherwise HTTP 409.

### POST /open-folder
Request `{"path": "D:\\Project_lip_service\\outputs"}`. Opens that folder in Explorer. `{"ok": true}`.

## Page requirements that come from this contract
- Content Security Policy for the page: `default-src 'self'; connect-src http://127.0.0.1:8780; img-src 'self' file: data:; media-src file: blob: http://127.0.0.1:8780; style-src 'self' 'unsafe-inline'; script-src 'self'`. No other network origin is ever allowed.
- The preload script exposes `window.lip = { api, token, pathFor(file), windowControl(action) }` where `windowControl` takes `"minimize"`, `"maximize"` or `"close"`.
