"""Audio and video file helpers (PyAV). No video re-encode: the shot is stream-copied."""
import av

AAC_RATE = 44100


def audio_duration(path: str) -> float:
    with av.open(str(path)) as c:
        stream = c.streams.audio[0]
        if stream.duration is not None:
            return float(stream.duration * stream.time_base)
        return float(c.duration) / av.time_base


def cut_audio_to_wav(src: str, dst: str, start: float = 0.0, end: float | None = None) -> float:
    """Decode src, keep [start, end) seconds, write 16 bit stereo 44.1 kHz wav. Returns seconds written."""
    resampler = av.AudioResampler(format="s16", layout="stereo", rate=AAC_RATE)
    written = 0
    first = int(start * AAC_RATE)
    last = None if end is None else int(end * AAC_RATE)
    with av.open(str(src)) as inp, av.open(str(dst), "w", format="wav") as out:
        out_stream = out.add_stream("pcm_s16le", rate=AAC_RATE, layout="stereo")
        pos = 0
        for frame in inp.decode(audio=0):
            for rf in resampler.resample(frame):
                n = rf.samples
                lo, hi = pos, pos + n
                pos = hi
                if hi <= first or (last is not None and lo >= last):
                    continue
                cut_lo = max(first - lo, 0)
                cut_hi = n if last is None else min(last - lo, n)
                if cut_lo == 0 and cut_hi == n:
                    piece = rf
                else:
                    arr = rf.to_ndarray()[:, cut_lo * 2:cut_hi * 2] if rf.format.is_packed else None
                    piece = av.AudioFrame.from_ndarray(arr, format="s16", layout="stereo")
                    piece.sample_rate = AAC_RATE
                piece.pts = None
                for pkt in out_stream.encode(piece):
                    out.mux(pkt)
                written += piece.samples
        for pkt in out_stream.encode(None):
            out.mux(pkt)
    return written / AAC_RATE


def mux_original_audio(video_path: str, audio_path: str, dst: str) -> None:
    """Copy the video stream as is, encode the original audio to AAC, write dst (mp4)."""
    with av.open(str(video_path)) as vin, av.open(str(audio_path)) as ain, av.open(str(dst), "w") as out:
        vs = vin.streams.video[0]
        out_v = out.add_stream_from_template(vs)
        out_a = out.add_stream("aac", rate=AAC_RATE, layout="stereo")
        out_a.bit_rate = 192000
        resampler = av.AudioResampler(format="fltp", layout="stereo", rate=AAC_RATE)

        for pkt in vin.demux(vs):
            if pkt.dts is None:
                continue
            pkt.stream = out_v
            out.mux(pkt)

        for frame in ain.decode(audio=0):
            for rf in resampler.resample(frame):
                for pkt in out_a.encode(rf):
                    out.mux(pkt)
        for pkt in out_a.encode(None):
            out.mux(pkt)
