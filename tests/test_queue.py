import time

from app.queue import JobQueue


def wait_for(q, job_id, status, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        j = next(j for j in q.snapshot() if j["id"] == job_id)
        if j["status"] == status:
            return j
        time.sleep(0.05)
    raise AssertionError(f"{job_id} never reached {status}: {q.snapshot()}")


def test_runs_in_order_and_survives_failure(tmp_path):
    seen = []

    def fake(spec, log):
        seen.append(spec.job_id)
        log("working")
        if spec.prompt == "boom":
            raise RuntimeError("nope")
        time.sleep(0.2)
        return f"out/{spec.job_id}.mp4"

    q = JobQueue(run_fn=fake, state_file=tmp_path / "q.json")
    a = q.add(shot="s.png", audio="a.wav", prompt="boom")
    b = q.add(shot="s.png", audio="a.wav", prompt="ok")
    c = q.add(shot="s.png", audio="a.wav", prompt="ok")
    assert q.cancel(c)
    wait_for(q, a, "failed")
    wait_for(q, b, "done")
    assert seen == [a, b]
    assert [j["status"] for j in q.snapshot()] == ["failed", "done", "cancelled"]


def test_restart_marks_running_as_failed(tmp_path):
    f = tmp_path / "q.json"
    f.write_text('[{"id":"x","status":"running","preset":"baseline","spec":{},"log":[],"result":null,"error":null}]')
    q = JobQueue(run_fn=lambda s, log: None, state_file=f)
    assert q.snapshot()[0]["status"] == "failed"
