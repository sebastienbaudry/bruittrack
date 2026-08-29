"""Unit and integration tests for Discomfort Log (Journal de gêne) and HD Spectral Zoom."""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import MagicMock

from bruittrack.config import Config
from bruittrack.store import EventStore
from bruittrack.viz import HTML_DASHBOARD, BruitTrackHandler


def test_store_discomfort_log_crud(tmp_path: Path) -> None:
    """Test EventStore discomfort log creation, retrieval, and deletion."""
    db_path = tmp_path / "test_disc.db"
    store = EventStore(db_path=db_path)

    # Initial state is empty
    assert store.get_discomfort_logs() == []

    # Insert log
    t0 = 1787000000.0
    log_id1 = store.log_discomfort(t0=t0, level=4, note="Nausée et vibration crâne")
    assert log_id1 > 0

    log_id2 = store.log_discomfort(t0=t0 + 100.0, level=2, note="Bourdonnement léger")
    assert log_id2 > log_id1

    # Retrieve logs (newest first)
    logs = store.get_discomfort_logs()
    assert len(logs) == 2
    assert logs[0]["id"] == log_id2
    assert logs[0]["level"] == 2
    assert logs[0]["note"] == "Bourdonnement léger"
    assert logs[1]["id"] == log_id1
    assert logs[1]["level"] == 4

    # Filter with since
    filtered = store.get_discomfort_logs(since=t0 + 50.0)
    assert len(filtered) == 1
    assert filtered[0]["id"] == log_id2

    # Delete log
    assert store.delete_discomfort_log(log_id1) is True
    assert len(store.get_discomfort_logs()) == 1
    assert store.delete_discomfort_log(9999) is False

    store.close()


def test_discomfort_api_endpoints(tmp_path: Path) -> None:
    """Test GET and POST endpoints for /api/discomfort."""
    db_path = tmp_path / "test_viz_disc.db"
    store = EventStore(db_path=db_path)
    config = Config()

    # 1. POST /api/discomfort
    handler_post = MagicMock()
    handler_post.store = store
    handler_post.config = config
    handler_post.path = "/api/discomfort"
    body = json.dumps({"level": 5, "note": "Crise et battements", "t0": 1787100000.0}).encode(
        "utf-8"
    )
    handler_post.headers = {"Content-Length": str(len(body))}
    handler_post.rfile = io.BytesIO(body)
    out_post = io.BytesIO()
    handler_post.wfile = out_post

    BruitTrackHandler.do_POST(handler_post)
    handler_post._send_json.assert_called_once()
    post_res = handler_post._send_json.call_args[0][0]
    assert post_res["ok"] is True
    log_id = post_res["id"]

    # 2. GET /api/discomfort
    handler_get = MagicMock()
    handler_get.store = store
    handler_get.config = config
    handler_get.path = "/api/discomfort?limit=10"
    BruitTrackHandler.do_GET(handler_get)
    handler_get._send_json.assert_called_once()
    get_res = handler_get._send_json.call_args[0][0]
    assert len(get_res) == 1
    assert get_res[0]["id"] == log_id
    assert get_res[0]["level"] == 5
    assert get_res[0]["note"] == "Crise et battements"

    # 3. POST /api/discomfort/<id>/delete
    handler_del = MagicMock()
    handler_del.store = store
    handler_del.config = config
    handler_del.path = f"/api/discomfort/{log_id}/delete"
    BruitTrackHandler.do_POST(handler_del)
    handler_del._send_json.assert_called_once()
    del_res = handler_del._send_json.call_args[0][0]
    assert del_res["ok"] is True
    assert store.get_discomfort_logs() == []

    store.close()


def test_dashboard_contains_discomfort_and_focus_controls() -> None:
    """Verify HTML_DASHBOARD contains HD Zoom and Discomfort Log UI elements."""
    # Discomfort UI elements
    assert "openDiscomfortModal" in HTML_DASHBOARD
    assert "discomfortModal" in HTML_DASHBOARD
    assert "discomfortTableBody" in HTML_DASHBOARD
    assert "submitDiscomfort" in HTML_DASHBOARD
    assert "fetchDiscomfortLogs" in HTML_DASHBOARD

    # Frequency Focus buttons (HD Spectral Zoom)
    assert "fFocusInfra" in HTML_DASHBOARD
    assert "fFocusHum" in HTML_DASHBOARD
    assert "fFocusHigh" in HTML_DASHBOARD
    assert "setFreqFocus" in HTML_DASHBOARD

    # HD Snapshot modal & Analysis banner elements
    assert "snapshotModal" in HTML_DASHBOARD
    assert "snapCanvas" in HTML_DASHBOARD
    assert "snapSpectrumCanvas" in HTML_DASHBOARD
    assert "snapPeaksBar" in HTML_DASHBOARD
    assert "snapAudioPlayer" in HTML_DASHBOARD
    assert "openSnapshotModal" in HTML_DASHBOARD
    assert "discomfortAnalysisBanner" in HTML_DASHBOARD
    assert "closeDiscomfortBanner" in HTML_DASHBOARD
    assert "copyCurrentDiscomfortReport" in HTML_DASHBOARD

    # Position : Le journal des gênes doit être placé AU-DESSUS des événements et clusters
    pos_disc = HTML_DASHBOARD.find("discomfortTableBody")
    pos_events = HTML_DASHBOARD.find("eventsTableBody")
    pos_clusters = HTML_DASHBOARD.find("clustersTableBody")
    assert pos_disc < pos_events and pos_disc < pos_clusters, (
        "Le journal des gênes doit être au-dessus des événements"
    )


def test_dsp_snapshot_and_beating_metrics() -> None:
    """Verify DspPipeline captures 30s rolling buffers and measures amplitude beating."""
    import numpy as np

    from bruittrack.dsp import DspPipeline

    dsp = DspPipeline(sample_rate=48000, decimation=48, freq_max=150.0)

    # Feed 30 blocks (3 seconds) of 15 Hz tone modulated at 1 Hz
    fs = 48000
    block_len = 4800  # 100 ms
    for b in range(30):
        t = (b * block_len + np.arange(block_len)) / fs
        # 1 Hz amplitude envelope (beating) on 15 Hz infrasound carrier
        env = 0.5 + 0.5 * np.sin(2.0 * np.pi * 1.0 * t)
        carrier = np.sin(2.0 * np.pi * 15.0 * t)
        signal = (env * carrier).astype(np.float32)
        raw_audio = np.column_stack([signal, signal])
        dsp.process_block(raw_audio)

    # Test beating metrics
    metrics = dsp.compute_beating_metrics()
    assert metrics["mod_infra_pct"] > 20.0  # Significant modulation detected in 2-35 Hz band
    assert isinstance(metrics["mod_period_s"], float)

    # Test snapshot extraction
    snap = dsp.get_snapshot()
    assert snap["fs"] == 1000
    assert snap["audio"].shape == (30000, 2)
    assert snap["psd_ch1"].shape == (300, dsp.n_bins)
    assert snap["psd_ch2"].shape == (300, dsp.n_bins)
    assert snap["mod_infra_pct"] == metrics["mod_infra_pct"]


def test_discomfort_snapshot_store_and_api(tmp_path: Path) -> None:
    """Test saving and retrieving snapshots via store and API."""
    import numpy as np

    db_path = tmp_path / "test_snap.db"
    snap_dir = tmp_path / "snapshots"
    store = EventStore(db_path=db_path)
    config = Config()
    config.storage.snapshots_dir = str(snap_dir)

    log_id = store.log_discomfort(t0=1787200000.0, level=4, note="Test snapshot")

    # Generate synthetic snapshot data
    n_bins = 300
    snap_data = {
        "fs": 1000,
        "freqs": np.linspace(2.0, 150.0, n_bins, dtype=np.float32),
        "audio": np.zeros((30000, 2), dtype=np.float32),
        "psd_ch1": np.zeros((300, n_bins), dtype=np.float32),
        "psd_ch2": np.zeros((300, n_bins), dtype=np.float32),
        "mod_infra_pct": 65.4,
        "mod_hum_pct": 12.3,
        "mod_period_s": 1.2,
    }

    # 1. Save snapshot
    npz_file = store.save_discomfort_snapshot(log_id, snap_data, snapshots_dir=snap_dir)
    assert npz_file.is_file()
    wav_file = snap_dir / f"snap_{log_id}.wav"
    assert wav_file.is_file()
    json_file = snap_dir / f"snap_{log_id}.json"
    assert json_file.is_file()

    # 2. Get discomfort logs with has_snapshot flag and metadata
    logs = store.get_discomfort_logs(snapshots_dir=snap_dir)
    assert len(logs) == 1
    assert logs[0]["has_snapshot"] is True
    assert logs[0]["mod_infra_pct"] == 65.4

    # 3. GET /api/discomfort/<id>/snapshot
    handler_snap = MagicMock()
    handler_snap.store = store
    handler_snap.config = config
    handler_snap.path = f"/api/discomfort/{log_id}/snapshot"
    BruitTrackHandler.do_GET(handler_snap)
    handler_snap._send_json.assert_called_once()
    snap_res = handler_snap._send_json.call_args[0][0]
    assert snap_res["mod_infra_pct"] == 65.4
    assert len(snap_res["freqs"]) == n_bins
    assert "mean_psd_ch1" in snap_res
    assert "peaks" in snap_res

    # 4. GET /api/discomfort/<id>/audio
    handler_audio = MagicMock()
    handler_audio.store = store
    handler_audio.config = config
    handler_audio.path = f"/api/discomfort/{log_id}/audio"
    out_audio = io.BytesIO()
    handler_audio.wfile = out_audio
    BruitTrackHandler.do_GET(handler_audio)
    handler_audio.send_response.assert_called_with(200)
    assert len(out_audio.getvalue()) > 0

    # 5. Delete discomfort log cleans snapshot files
    assert store.delete_discomfort_log(log_id, snapshots_dir=snap_dir) is True
    assert not npz_file.is_file()
    assert not wav_file.is_file()
    assert not json_file.is_file()

    store.close()
