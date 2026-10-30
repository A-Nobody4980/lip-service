"""Sample files for the tests, made on the fly so the tests need nothing outside the repo."""
import wave

import av
import numpy as np
import pytest
from PIL import Image


@pytest.fixture(scope="session")
def sample_wav(tmp_path_factory):
    """20 s of stereo audio with a changing pitch and volume."""
    rate, seconds = 44100, 20
    t = np.arange(rate * seconds) / rate
    mono = 0.5 * np.sin(2 * np.pi * (220 + 40 * np.sin(t)) * t) * (0.4 + 0.6 * np.abs(np.sin(t / 2)))
    pcm = (np.stack([mono, mono], axis=1) * 32767).astype(np.int16)
    path = tmp_path_factory.mktemp("media") / "sample.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return str(path)


@pytest.fixture(scope="session")
def sample_shot(tmp_path_factory):
    """A 1376x768 picture, the size of the usual test shot."""
    x = np.linspace(0, 255, 1376, dtype=np.uint8)[None, :].repeat(768, axis=0)
    y = np.linspace(0, 255, 768, dtype=np.uint8)[:, None].repeat(1376, axis=1)
    path = tmp_path_factory.mktemp("media") / "shot.png"
    Image.fromarray(np.stack([x, y, 255 - x], axis=2)).save(path)
    return str(path)


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory):
    """A 5 s, 25 fps, 832x480 video with no sound."""
    path = tmp_path_factory.mktemp("media") / "sample.mp4"
    with av.open(str(path), "w") as out:
        stream = out.add_stream("mpeg4", rate=25)
        stream.width, stream.height, stream.pix_fmt = 832, 480, "yuv420p"
        for i in range(125):
            frame = av.VideoFrame.from_ndarray(np.full((480, 832, 3), (i * 2) % 255, dtype=np.uint8), format="rgb24")
            for pkt in stream.encode(frame):
                out.mux(pkt)
        for pkt in stream.encode(None):
            out.mux(pkt)
    return str(path)
