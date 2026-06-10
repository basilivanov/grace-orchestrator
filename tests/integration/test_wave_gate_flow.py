"""Block N: Wave Gate Flow integration tests — 3 tests."""
import subprocess
import pytest


def _init_repo(path):
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "T"], check=True)
    subprocess.run(["git", "-C", str(path), "checkout", "-b", "main"], check=True)
    (path / "README.md").write_text("hello")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "init"], check=True)


@pytest.mark.asyncio
async def test_full_two_wave_e2e(api, tmp_path):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "WGATE", "waves": [
            {"title": "W1", "packets": [{"title": "A", "scope": ["a.py"]}, {"title": "B", "scope": ["b.py"]}]},
            {"title": "W2", "packets": [{"title": "C", "scope": ["c.py"]}]}]}})
    fid = r.json()["data"]["feature_id"]
    pids = r.json()["data"]["packets"]
    w1_pids = pids[:2]
    w2_pids = pids[2:]

    repo = tmp_path / "repo"
    _init_repo(repo)

    # Plan leaves all packets in draft; wave gate transitions W1 to ready.
    from grace_control.core.wave_gate import check_wave_gates
    check_wave_gates()

    # Verify W1 ready, W2 draft
    for p in w1_pids:
        r = await api.get(f"/api/packets/{p}")
        assert r.json()["data"]["state"] == "ready"
    for p in w2_pids:
        r = await api.get(f"/api/packets/{p}")
        assert r.json()["data"]["state"] == "draft"

    # Execute W1
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    for idx, p in enumerate(w1_pids):
        await api.post("/api/packets/claim", json={"worker_id": "w1"})
        await api.post(f"/api/packets/{p}/release",
                       json={"worker_id": "w1", "status": "accepted", "result": {"accepted": True}})
        await api.post(f"/api/packets/{p}/merge", json={
            "worktree_path": str(tmp_path / f"wt_{idx}"),
            "branch_name": "HEAD",
            "target_repo_root": str(repo),
            "commit_sha": "abc" * 10,
        })

    # Trigger wave gate
    check_wave_gates()

    for p in w2_pids:
        r = await api.get(f"/api/packets/{p}")
        assert r.json()["data"]["state"] == "ready"

    # Execute W2
    for idx, p in enumerate(w2_pids):
        await api.post("/api/packets/claim", json={"worker_id": "w1"})
        await api.post(f"/api/packets/{p}/release",
                       json={"worker_id": "w1", "status": "accepted", "result": {"accepted": True}})
        await api.post(f"/api/packets/{p}/merge", json={
            "worktree_path": str(tmp_path / f"wt2_{idx}"),
            "branch_name": "HEAD",
            "target_repo_root": str(repo),
            "commit_sha": "abc" * 10,
        })

    # Trigger feature gate
    from grace_control.core.feature_gate import check_feature_completion
    check_feature_completion()

    r = await api.get(f"/api/features/{fid}")
    assert r.json()["data"]["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_wave2_not_claimable_before_wave1_done(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "WG2", "waves": [
            {"title": "W1", "packets": [{"title": "A", "scope": ["a.py"]}]},
            {"title": "W2", "packets": [{"title": "B", "scope": ["b.py"]}]}]}})
    pids = r.json()["data"]["packets"]

    await api.post("/api/workers/register", json={"worker_id": "w1"})
    r = await api.post("/api/packets/claim", json={"worker_id": "w1"})
    claimed = r.json()["data"]["packet_id"]
    assert claimed == pids[0]  # W1 packet


@pytest.mark.asyncio
async def test_wave_gate_check_idempotent_via_api(api, tmp_path):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "WG3", "waves": [
            {"title": "W1", "packets": [{"title": "A", "scope": ["a.py"]}]},
            {"title": "W2", "packets": [{"title": "B", "scope": ["b.py"]}]}]}})
    pids = r.json()["data"]["packets"]
    w2_pid = pids[1]

    repo = tmp_path / "repo"
    _init_repo(repo)

    from grace_control.core.wave_gate import check_wave_gates
    check_wave_gates()

    await api.post("/api/workers/register", json={"worker_id": "w1"})
    await api.post("/api/packets/claim", json={"worker_id": "w1"})
    await api.post(f"/api/packets/{pids[0]}/release",
                   json={"worker_id": "w1", "status": "accepted", "result": {"accepted": True}})
    await api.post(f"/api/packets/{pids[0]}/merge", json={
        "worktree_path": str(tmp_path / "wt"),
        "branch_name": "HEAD",
        "target_repo_root": str(repo),
        "commit_sha": "abc" * 10,
    })

    check_wave_gates()
    check_wave_gates()  # second call

    r = await api.get(f"/api/packets/{w2_pid}")
    assert r.json()["data"]["state"] == "ready"
