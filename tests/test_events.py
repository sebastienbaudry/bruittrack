"""Tests for EventDetector, Fingerprinting, and ClusterIndex."""

import tempfile

import numpy as np
import pytest

from bruittrack.events import (
    ClusterIndex,
    EventDetector,
    decode_fingerprint,
    encode_fingerprint,
    fingerprints_match,
)


def test_fingerprint_encode_decode_roundtrip() -> None:
    spectrum = np.zeros(99, dtype=np.float32)
    spectrum[20] = 15.0  # Peak
    spectrum[18] = 5.0
    spectrum[19] = 10.0
    spectrum[21] = 12.0
    spectrum[22] = 4.0

    fp = encode_fingerprint(
        bin_peak=20,
        emergence_spectrum=spectrum,
        dominant_ch=0,
        off_ms=-3.2,
    )
    assert len(fp) == 16

    decoded = decode_fingerprint(fp)
    assert decoded.version == 1
    assert decoded.bin_peak == 20
    assert decoded.dominant_ch == 0
    assert decoded.delay_class == -3
    assert decoded.neighbors[2] == 7  # Peak quantized to 7


def _fp_at(bin_peak: int) -> bytes:
    spectrum = np.zeros(99, dtype=np.float32)
    spectrum[bin_peak] = 20.0
    return encode_fingerprint(bin_peak, spectrum, dominant_ch=0, off_ms=0.0)


def test_fingerprints_match_max_bin_delta() -> None:
    """Peak-bin tolerance is explicit via max_bin_delta (I44)."""
    base = _fp_at(30)

    # Default (1 bin): Δ=1 ok, Δ=2 rejected
    assert fingerprints_match(base, _fp_at(31))
    assert not fingerprints_match(base, _fp_at(32))

    # max_bin_delta=3: Δ=3 ok, Δ=4 rejected
    assert fingerprints_match(base, _fp_at(33), 3)
    assert not fingerprints_match(base, _fp_at(34), 3)


def test_event_detector_cluster_tolerance_hz() -> None:
    """cluster_freq_tolerance_hz → bins (resolution = 48000/2^16 ≈ 0.48828125 Hz)."""
    res = 0.48828125
    det_tight = EventDetector(cluster_freq_tolerance_hz=0.5)
    assert det_tight.cluster_max_bin_delta == max(0, round(0.5 / res))
    assert det_tight.cluster_index.max_bin_delta == det_tight.cluster_max_bin_delta

    det_wide = EventDetector(cluster_freq_tolerance_hz=1.47)
    expected_wide = max(0, round(1.47 / res))  # ≈ 3 bins
    assert det_wide.cluster_index.max_bin_delta == expected_wide


def test_cluster_index_max_bin_delta() -> None:
    """ClusterIndex honors its tolerance when matching (I44)."""
    index = ClusterIndex(max_bin_delta=3)
    c1, is_new = index.match_or_create(_fp_at(30))
    assert is_new
    # Δ=4 would be rejected by default (1 bin) but accepted at 3 bins? No: 4 > 3 → new cluster
    c2, is_new2 = index.match_or_create(_fp_at(33))
    assert not is_new2 and c2 == c1
    c3, is_new3 = index.match_or_create(_fp_at(34))
    assert is_new3 and c3 != c1


def test_fingerprints_match() -> None:
    spectrum1 = np.zeros(99, dtype=np.float32)
    spectrum1[30] = 20.0
    fp1 = encode_fingerprint(30, spectrum1, dominant_ch=0, off_ms=2.0)

    # Slight variation in peak bin (+1) and delay (+1 ms) with same peak shape -> should match
    spectrum2 = np.zeros(99, dtype=np.float32)
    spectrum2[31] = 20.0
    fp2 = encode_fingerprint(31, spectrum2, dominant_ch=0, off_ms=3.0)
    assert fingerprints_match(fp1, fp2)

    # Big variation in peak bin (+5) -> should NOT match
    spectrum3 = np.zeros(99, dtype=np.float32)
    spectrum3[35] = 20.0
    fp3 = encode_fingerprint(35, spectrum3, dominant_ch=0, off_ms=2.0)
    assert not fingerprints_match(fp1, fp3)


def test_cluster_index() -> None:
    index = ClusterIndex()
    spectrum_a1 = np.zeros(99, dtype=np.float32)
    spectrum_a1[15] = 10.0
    fp_a1 = encode_fingerprint(15, spectrum_a1, dominant_ch=0, off_ms=0.0)

    spectrum_a2 = np.zeros(99, dtype=np.float32)
    spectrum_a2[16] = 10.0
    fp_a2 = encode_fingerprint(16, spectrum_a2, dominant_ch=0, off_ms=1.0)

    spectrum_b = np.zeros(99, dtype=np.float32)
    spectrum_b[45] = 10.0
    fp_b = encode_fingerprint(45, spectrum_b, dominant_ch=1, off_ms=5.0)

    c1, is_new1 = index.match_or_create(fp_a1)
    assert is_new1
    assert c1 == 1

    # fp_a2 should match cluster 1
    c2, is_new2 = index.match_or_create(fp_a2)
    assert not is_new2
    assert c2 == 1

    # fp_b should create cluster 2
    c3, is_new3 = index.match_or_create(fp_b)
    assert is_new3
    assert c3 == 2


def test_event_detector_debounce_and_emission() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        det = EventDetector(
            threshold_db=10.0,
            hysteresis_db=3.0,
            debounce_ticks=3,
            max_duration_s=30.0,
            exemplars_dir=tmpdir,
        )

        audio_buf = np.zeros((512, 2), dtype=np.float32)
        quiet = np.zeros(99, dtype=np.float32)
        loud = np.zeros(99, dtype=np.float32)
        loud[25] = 18.0  # +18 dB emergence on bin 25

        # Tick 1: Loud (candidate 1)
        evs = det.update(loud, loud, audio_buf, off_ms=0.0, unix_time=1000.0)
        assert len(evs) == 0
        assert not det.is_active

        # Tick 2: Loud (candidate 2)
        evs = det.update(loud, loud, audio_buf, off_ms=0.0, unix_time=1000.1)
        assert len(evs) == 0

        # Tick 3: Loud (candidate 3 -> validated active!)
        evs = det.update(loud, loud, audio_buf, off_ms=0.0, unix_time=1000.2)
        assert len(evs) == 0
        assert det.is_active

        # Tick 4: Loud
        evs = det.update(loud, loud, audio_buf, off_ms=0.0, unix_time=1000.3)
        assert len(evs) == 0

        # Tick 5: Quiet -> Drop below hysteresis (release)
        evs = det.update(quiet, quiet, audio_buf, off_ms=0.0, unix_time=1000.4)
        assert len(evs) == 1
        ev = evs[0]
        assert ev.bin_i == 25
        assert ev.lvl_g == 18.0
        assert ev.lvl_d == 18.0
        assert ev.dur > 0
        assert ev.cluster == 1
        assert not det.is_active


@pytest.mark.parametrize("record_exemplars", [True, False])
def test_record_exemplars_toggle(tmp_path, record_exemplars: bool) -> None:
    """record_exemplars=False : aucun fichier audio brut écrit, bit FLAG_EXEMPLAR absent."""
    from bruittrack.events import FLAG_EXEMPLAR

    det = EventDetector(
        threshold_db=10.0,
        hysteresis_db=3.0,
        debounce_ticks=3,
        max_duration_s=30.0,
        exemplars_dir=tmp_path,
        record_exemplars=record_exemplars,
    )
    audio_buf = np.zeros((512, 2), dtype=np.float32)
    quiet = np.zeros(99, dtype=np.float32)
    loud = np.zeros(99, dtype=np.float32)
    loud[25] = 18.0
    for _ in range(3):
        det.update(loud, loud, audio_buf, off_ms=0.0, unix_time=1000.0)
    ev = det.update(quiet, quiet, audio_buf, off_ms=0.0, unix_time=1000.3)[0]
    ex_file = tmp_path / "ex_1.raw"
    if record_exemplars:
        assert ex_file.is_file()
        assert bool(ev.flags & FLAG_EXEMPLAR)
    else:
        assert not ex_file.is_file(), "aucun fichier audio ne doit être écrit"
        assert not bool(ev.flags & FLAG_EXEMPLAR)


def test_event_detector_ignores_dc_bin() -> None:
    """A DC (bin 0, 0 Hz) spike must never create an event."""
    with tempfile.TemporaryDirectory() as tmpdir:
        det = EventDetector(
            threshold_db=10.0,
            hysteresis_db=3.0,
            debounce_ticks=3,
            max_duration_s=30.0,
            exemplars_dir=tmpdir,
        )

        audio_buf = np.zeros((512, 2), dtype=np.float32)
        quiet = np.zeros(99, dtype=np.float32)
        dc_loud = np.zeros(99, dtype=np.float32)
        dc_loud[0] = 40.0  # Huge +40 dB DC emergence

        t = 2000.0
        for _ in range(10):  # Long DC spike: must stay inactive
            evs = det.update(dc_loud, dc_loud, audio_buf, off_ms=0.0, unix_time=t)
            assert evs == []
            t += 0.1
        assert not det.is_active

        # A real bin still triggers normally (mixed DC + bin 25)
        mixed = dc_loud.copy()
        mixed[25] = 18.0
        for i in range(3):
            evs = det.update(mixed, mixed, audio_buf, off_ms=0.0, unix_time=t)
            t += 0.1
            if i == 2:
                assert det.is_active
        evs = det.update(quiet, quiet, audio_buf, off_ms=0.0, unix_time=t)
        assert len(evs) == 1
        assert evs[0].bin_i == 25


class TestComputeFlags:
    """_compute_flags: bit3 over-legal-limit (CSP R1336-7)."""

    def _det(self, peak_g, peak_d, t0_unix):
        from bruittrack.events import EventDetector

        det = EventDetector()
        det.peak_lvl_g = peak_g
        det.peak_lvl_d = peak_d
        det.t0_unix = t0_unix
        return det

    def test_below_limit_no_flag(self):
        import time as _t

        from bruittrack.legal import emergence_limit

        ts = 1_750_000_000.0
        lt = _t.localtime(ts)
        limite = emergence_limit(lt.tm_hour, lt.tm_min, 2.0)
        det = self._det(max(0.0, limite - 4.0), 0.0, ts)
        assert self._mask(det, 2.0) == 0

    def test_above_limit_flag_set(self):
        import time as _t

        from bruittrack.legal import emergence_limit

        ts = 1_750_000_000.0
        lt = _t.localtime(ts)
        limite = emergence_limit(lt.tm_hour, lt.tm_min, 2.0)
        det = self._det(limite + 3.0, 0.0, ts)
        from bruittrack.events import FLAG_OVER_LEGAL

        assert self._mask(det, 2.0) & FLAG_OVER_LEGAL

    def test_cum_duration_used_for_chained_segments(self):
        """I58 : la limite est évaluée sur la durée cumulée de l'épisode.

        Un bruit continu découpé en segments de 30 s ne doit pas rester
        bloqué au correctif +6 dB : chaque segment intègre la durée des
        segments précédents (CSP R1336-7, duree_cumulee).
        """
        import time as _t

        from bruittrack.legal import emergence_limit

        ts = 1_750_000_000.0
        lt = _t.localtime(ts)
        limite_segment = emergence_limit(lt.tm_hour, lt.tm_min, 2.0)  # +6 dB
        dur_total = 7320.0  # ~2 h 02 : correctif +2 dB
        limite_episode = emergence_limit(lt.tm_hour, lt.tm_min, dur_total)
        assert limite_episode < limite_segment
        peak = (limite_segment + limite_episode) / 2.0
        det = self._det(peak, 0.0, ts)

        # Sans chaînage : le pic est sous le seuil segment (+6 dB).
        det.cum_duration_s = 0.0
        assert self._mask(det, 30.0) == 0

        # Avec chaînage : le seuil redescend → dépassement flagué.
        from bruittrack.events import FLAG_OVER_LEGAL

        det.cum_duration_s = dur_total - 30.0
        assert self._mask(det, 30.0) & FLAG_OVER_LEGAL

    @staticmethod
    def _mask(det, duration_s):
        return det._compute_flags(duration_s)


class TestCumDurationChain:
    """I58 : épisode continu chaîné → correction de durée cumulée (CSP R1336-7)."""

    def test_chained_segments_get_longer_correction(self, tmp_path):
        import time as _t

        from bruittrack.events import FLAG_OVER_LEGAL, EventDetector
        from bruittrack.legal import emergence_limit

        det = EventDetector(
            threshold_db=10.0,
            debounce_ticks=2,
            exemplars_dir=tmp_path,
        )
        t0 = 1_750_000_000.0
        lt = _t.localtime(t0)
        # Pic entre le correctif « ≤30 s » (+6) et « >5 min » (+4).
        limite_segment = emergence_limit(lt.tm_hour, lt.tm_min, 30.0)
        limite_c90 = emergence_limit(lt.tm_hour, lt.tm_min, 90.0)
        peak = (limite_segment + limite_c90) / 2.0

        audio_buf = np.zeros((512, 2), dtype=np.float32)
        emer = np.zeros(99, dtype=np.float32)
        emer[25] = peak
        events: list = []
        t = t0
        for _ in range(1200):  # 120 s de bruit continu
            events.extend(det.update(emer, emer.copy(), audio_buf, off_ms=0.0, unix_time=t))
            t += 0.1
        # Coupure → dernier segment.
        events.extend(det.update(np.zeros(99), np.zeros(99), audio_buf, off_ms=0.0, unix_time=t))

        assert len(events) >= 3, "le plafond 30 s doit découper l'épisode en segments"
        # Les premiers segments (cum ≤ 60 s, +6 dB) sont conformes ; après
        # ~90 s cumulés le correctif redescend à +5 dB → le pic dépasse.
        assert events[0].flags & FLAG_OVER_LEGAL == 0
        assert any(e.flags & FLAG_OVER_LEGAL for e in events[-3:]), (
            "le segment final doit être évalué sur la durée cumulée de l'épisode"
        )
