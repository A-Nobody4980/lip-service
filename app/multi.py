"""Several singers in one shot: turn the marked faces into per-singer masks and audio slots."""
import wave
from pathlib import Path

import av
import numpy as np
from PIL import Image, ImageChops

from .masks import box_mask, orig_box_to_frame
from .media import cut_audio_to_wav


def person_boxes(singers, img_w, img_h):
    """One box per marked face, in original image pixels: head to the bottom of the picture, about 2.4 face
    widths wide. Neighbours that overlap are split halfway between their face centres."""
    boxes = []
    for s in singers:
        cx, cy, fw = s["x"] * img_w, s["y"] * img_h, 2 * s["r"] * img_w
        boxes.append([cx - 1.2 * fw, cy - 1.0 * fw, cx + 1.2 * fw, float(img_h)])
    order = sorted(range(len(boxes)), key=lambda i: (boxes[i][0] + boxes[i][2]) / 2)
    for a, b in zip(order, order[1:]):
        if boxes[a][2] > boxes[b][0]:
            mid = ((boxes[a][0] + boxes[a][2]) / 2 + (boxes[b][0] + boxes[b][2]) / 2) / 2
            boxes[a][2] = boxes[b][0] = mid
    return [[max(0.0, b[0]), max(0.0, b[1]), min(float(img_w), b[2]), min(float(img_h), b[3])] for b in boxes]


def write_masks(singers, shot_path, width, height, out_dir: Path, prefix: str, background: bool = False):
    """Writes one mask png per singer into out_dir and returns the file names. Boxes are mapped through the
    same centre crop the workflow applies to the shot. With background=True a last mask is added that is white
    wherever no singer is marked: the model gives that region to nobody, so unmarked people stay quiet."""
    with Image.open(shot_path) as im:
        size = im.size
    names, images = [], []
    for i, box in enumerate(person_boxes(singers, *size)):
        frac = orig_box_to_frame(box, size, width, height)
        if frac[2] - frac[0] < 0.02 or frac[3] - frac[1] < 0.02:
            raise ValueError(f"Singer {i + 1} is outside the part of the picture that gets rendered. "
                             "The sides of the picture are cut to fit the frame.")
        name = f"{prefix}_mask{i + 1}.png"
        mask = box_mask(frac, width, height)
        mask.save(out_dir / name)
        names.append(name)
        images.append(mask)
    if background:
        union = images[0]
        for im in images[1:]:
            union = ImageChops.lighter(union, im)
        name = f"{prefix}_maskbg.png"
        ImageChops.invert(union).save(out_dir / name)
        names.append(name)
    return names


def cut_singer_audios(paths, start, end, work: Path):
    """Cuts every singer's own track with the same start and end. Returns (files, shortest length in seconds)."""
    files, lengths = [], []
    for i, p in enumerate(paths, start=1):
        dst = work / f"singer{i}_audio.wav"
        lengths.append(cut_audio_to_wav(p, str(dst), start, end))
        files.append(dst)
    return files, min(lengths)


def mix_wavs(paths, dst):
    """Adds the singers' tracks together (scaled down only if it would clip). Used as the sound on a finished
    shot when each singer has a separate track."""
    arrays = []
    for p in paths:
        with wave.open(str(p)) as w:
            arrays.append(np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32))
            rate, ch = w.getframerate(), w.getnchannels()
    n = min(len(a) for a in arrays)
    total = sum(a[:n] for a in arrays)
    peak = np.abs(total).max()
    if peak > 32000:
        total = total * (32000 / peak)
    with wave.open(str(dst), "wb") as o:
        o.setnchannels(ch)
        o.setsampwidth(2)
        o.setframerate(rate)
        o.writeframes(total.astype(np.int16).tobytes())
    return dst


def make_silence(dst, seconds, rate=44100):
    """A silent stereo wav. Used as a second audio slot so a lone marked singer can be told apart from everyone else."""
    with wave.open(str(dst), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\0\0\0\0" * int(seconds * rate))
    return dst
