import av

from app.media import audio_duration, cut_audio_to_wav, mux_original_audio


def test_cut_and_duration(tmp_path, sample_wav):
    dst = tmp_path / "cut.wav"
    cut_audio_to_wav(sample_wav, str(dst), 9.0, 14.0)
    assert abs(audio_duration(str(dst)) - 5.0) < 0.02


def test_mux_keeps_video_and_adds_audio(tmp_path, sample_wav, sample_video):
    cut = tmp_path / "cut.wav"
    cut_audio_to_wav(sample_wav, str(cut), 9.0, 14.0)
    out = tmp_path / "out.mp4"
    mux_original_audio(sample_video, str(cut), str(out))
    with av.open(str(out)) as c:
        assert len(c.streams.video) == 1 and len(c.streams.audio) == 1
        assert abs(float(c.streams.audio[0].duration * c.streams.audio[0].time_base) - 5.0) < 0.1
        n = sum(1 for _ in c.decode(video=0))
    with av.open(sample_video) as c:
        assert n == sum(1 for _ in c.decode(video=0))
