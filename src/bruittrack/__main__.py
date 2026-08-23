"""CLI Entrypoint for BruitTrack.

Subcommands:
- devices: List audio devices
- test: Live terminal monitoring (no X11 / GUI required)
- start: Start capture daemon
- viz: Start web visualization server
- stats: Display database stats and top sound clusters
"""

from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from bruittrack import __version__
from bruittrack.capture import AudioCapture, MockAudioCapture, list_audio_devices

# Fréquence de la ligne d'état FloorTracker en mode --verbose-floor (10 s à 100 ms/tick).
FLOOR_HEALTH_EVERY_TICKS = 100

# Budget performances (matrice M9 / GOAL.md c.5) — zéro constant magique.
CPU_MAX_PCT = 15
RSS_MAX_KB = 153_600
PERF_SAMPLE_SECONDS = 15


def format_floor_health(floor_tracker) -> str:
    """Une ligne lisible de l'état du FloorTracker (G / D) pour --verbose-floor."""
    f1, f2 = floor_tracker.get_floor()
    status = "OK" if floor_tracker.is_warmed_up else "warmup"
    return (
        f"[floor] {status} | médiane {float(np.median(f1)):.1f} / {float(np.median(f2)):.1f} dB"
        f" | ptp {float(np.ptp(f1)):.1f} / {float(np.ptp(f2)):.1f} dB"
    )
from bruittrack.config import load_config
from bruittrack.pipeline import Engine
from bruittrack.store import EventStore
from bruittrack.viz import run_viz_server


def cmd_devices(args: argparse.Namespace) -> int:
    """List available audio input devices."""
    try:
        devices = list_audio_devices()
    except Exception as e:
        print(f"Erreur lors de la détection des périphériques audio : {e}")
        return 1

    if not devices:
        print("Aucun périphérique d'entrée audio détecté.")
        return 0

    print("Périphériques d'entrée audio disponibles (PortAudio/ALSA) :")
    print("-" * 65)
    for dev in devices:
        default_tag = " [PAR DÉFAUT]" if dev["is_default"] else ""
        print(
            f"ID {dev['id']:2d} : {dev['name']}{default_tag} "
            f"({dev['max_input_channels']} canaux, {int(dev['default_samplerate'])} Hz)"
        )
    print("-" * 65)
    print("Pour configurer votre périphérique, renseignez `device` dans config.toml.")
    return 0


def cmd_test(args: argparse.Namespace) -> int:
    """Run live terminal monitoring for testing without GUI."""
    config = load_config(args.config)
    seconds = args.seconds

    capture: AudioCapture | MockAudioCapture
    if args.synthetic:
        print("Mode synthétique activé (génération de signaux purs sans carte son)...")
        capture = MockAudioCapture(
            sample_rate=config.audio.sample_rate,
            channels=config.audio.channels,
            block_size=config.audio.block_size,
            frequency_hz=23.5,
        )
    else:
        try:
            capture = AudioCapture(
                device=config.audio.device,
                sample_rate=config.audio.sample_rate,
                channels=config.audio.channels,
                block_size=config.audio.block_size,
            )
        except Exception as e:
            print(f"Impossible d'ouvrir le périphérique audio ({e}). Bascule en mode synthétique...")
            capture = MockAudioCapture(
                sample_rate=config.audio.sample_rate,
                channels=config.audio.channels,
                block_size=config.audio.block_size,
            )

    # Use in-memory store for test mode to avoid polluting production DB
    from bruittrack.store import EventStore
    test_store = EventStore(db_path=":memory:")
    engine = Engine(config=config, capture=capture, store=test_store)

    print(f"Test en direct pendant {seconds} secondes (Ctrl+C pour quitter)...")
    print(f"Résolution spectrale : {engine.dsp.bin_resolution:.3f} Hz/bin | Bins 0..48 Hz")
    print("-" * 75)
    print("  Tick  | Échauffement | Max Émergence (G / D) | Pic Fréq | Événements")
    print("-" * 75)

    start_time = time.monotonic()
    tick = 0

    capture.start()
    try:
        while time.monotonic() - start_time < seconds:
            raw_block = capture.get_block(timeout=0.5)
            if raw_block is None:
                continue

            tick += 1
            _psd1, _psd2, em1, em2, events = engine.step(raw_block)

            max_em1 = float(np.max(em1))
            max_em2 = float(np.max(em2))
            peak_bin = int(np.argmax(np.maximum(em1, em2)))
            peak_freq = peak_bin * engine.dsp.bin_resolution

            if getattr(args, "verbose_floor", False) and tick % FLOOR_HEALTH_EVERY_TICKS == 0:
                print(f"{tick:6d}  | {format_floor_health(engine.floor_tracker)}")

            warm_str = "OK" if engine.floor_tracker.is_warmed_up else f"{tick}/{config.detector.warmup_ticks}"
            event_str = f"DETECTÉ ! #{events[0].cluster} ({events[0].dur}s)" if events else ""

            # Visual bar
            em_bar_len = min(20, max(0, int(max(max_em1, max_em2) / 2)))
            bar = "#" * em_bar_len

            if tick % 5 == 0 or events:  # Print every 0.5s or on event
                print(
                    f"{tick:6d}  | {warm_str:12s} | {max_em1:+5.1f} / {max_em2:+5.1f} dB [{bar:<20s}] | {peak_freq:5.1f} Hz | {event_str}"
                )

    except KeyboardInterrupt:
        print("\nTest interrompu par l'utilisateur.")
    finally:
        engine.stop()

    print("-" * 75)
    print("Test terminé avec succès.")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    """Start the capture engine daemon."""
    config = load_config(args.config)
    engine = Engine(config=config)

    def handle_signal(sig: int, frame: Any) -> None:
        print("\nSignal d'arrêt reçu, fermeture propre...")
        engine.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    print(f"Démarrage du démon BruitTrack (v{__version__})...")
    print(f"Capture : 48 kHz / 2 ch -> décimation x{config.audio.decimation} -> 1000 Hz")
    print(f"Base de données : {config.storage.db_path}")

    engine.start()
    return 0


def cmd_viz(args: argparse.Namespace) -> int:
    """Start the web visualization server."""
    config = load_config(args.config)
    if args.port:
        config.viz.port = args.port
    if args.host:
        config.viz.host = args.host

    run_viz_server(config)
    return 0


def _exemplar_to_wav(raw_file: Path, sample_rate: int = 1000) -> bytes:
    """Convert a float16 raw excerpt (2 ch interleaved) to an int16 WAV blob.

    BUG-05: SoX cannot interpret IEEE-754 half directly; emit a proper WAV.
    """
    import io
    import wave

    data = np.frombuffer(raw_file.read_bytes(), dtype=np.float16)
    if data.size % 2:
        data = data[:-1]
    i16 = (np.clip(data, -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(i16.tobytes())
    return buf.getvalue()


def cmd_stats(args: argparse.Namespace) -> int:
    """Display database statistics and top sound clusters."""
    config = load_config(args.config)
    store = EventStore(
        db_path=config.storage.db_path,
        batch_size=config.storage.batch_size,
    )

    if args.play:
        # Play exemplar audio for a cluster
        cluster_id = args.play
        raw_file = Path(config.storage.exemplars_dir) / f"ex_{cluster_id}.raw"
        if not raw_file.is_file():
            print(f"Aucun extrait audio exemplaire trouvé pour le cluster #{cluster_id} ({raw_file})")
            return 1

        print(f"Lecture de l'exemplaire #{cluster_id} (256 ms @ 1kHz, 2 canaux)...")
        # Convert float16 raw to int16 WAV in a temp file, then play
        import tempfile

        wav_path = Path(tempfile.gettempdir()) / f"bruittrack_ex_{cluster_id}.wav"
        tmp_name = str(wav_path)
        try:
            wav_path.write_bytes(_exemplar_to_wav(raw_file))
            subprocess.run(["play", tmp_name], check=True)
        except FileNotFoundError:
            print("Commande 'play' (SoX) non disponible. Utilisez le serveur web `viz` pour écouter.")
        finally:
            wav_path.unlink(missing_ok=True)
        return 0

    stats = store.get_stats()
    clusters = store.get_clusters_summary()

    if getattr(args, "json", False):
        payload = {
            "db_path": str(config.storage.db_path),
            "total_events": stats.get("total_events", 0),
            "total_clusters": stats.get("total_clusters", 0),
            "db_size_bytes": stats.get("db_size_bytes", 0),
            "avg_dur": stats.get("avg_dur"),
            "top_clusters": [dict(c) for c in clusters[:15]],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0

    print(f"=== Statistiques BruitTrack ({config.storage.db_path}) ===")
    print(f"Total événements enregistrés : {stats.get('total_events', 0)}")
    print(f"Nombre de clusters distincts : {stats.get('total_clusters', 0)}")
    size_kb = stats.get("db_size_bytes", 0) / 1024.0
    print(f"Taille de la base de données : {size_kb:.1f} Ko")
    if stats.get("avg_dur"):
        print(f"Durée moyenne des événements : {stats['avg_dur']:.2f} s")

    if clusters:
        print("\n--- Top Groupes Récurrents (Clusters) ---")
        print(" Cluster | Occurrences | Fréq Moy (Hz) | Max Émergence (G / D) | Statut")
        print("-" * 72)
        for c in clusters[:15]:
            status = "Ignoré" if (c["flags"] & 2) else "Actif"
            print(
                f" #{c['cluster_id']:6d} | {c['event_count']:11d} | {c['avg_freq']:13.1f} | "
                f"+{c['max_lvl_g']:4.1f} / +{c['max_lvl_d']:4.1f} dB  | {status}"
            )
    else:
        print("\nAucun événement ni cluster dans la base.")

    return 0


def cmd_perf(args: argparse.Namespace) -> int:
    """Échantillonner le CPU/RSS d'un PID et les comparer aux budgets M9."""
    import os as _os
    import platform

    pid = args.pid or _os.getpid()
    if platform.system() != "Linux":
        print("La commande perf nécessite /proc (Linux).")
        return 1

    def sample() -> tuple[int, int]:
        stat = Path(f"/proc/{pid}/stat").read_text()
        fields = stat.rsplit(")", 1)[1].split()
        cps = int(fields[11]) + int(fields[12])  # utime+stime en jiffies
        rss_kb = int(fields[21]) * 4  # pages de 4 Ko
        return cps, rss_kb

    t0, _rss0 = sample()
    print(f"Échantillonnage PID {pid}... (fenêtre {PERF_SAMPLE_SECONDS})")
    time.sleep(PERF_SAMPLE_SECONDS)
    t1, rss1 = sample()
    if t1 == t0:
        print("Impossible de mesurer le CPU (PID absent ou accès /proc refusé). Code: 1")
        return 1
    cpu_pct = (t1 - t0) * 100 / (PERF_SAMPLE_SECONDS * 100)
    rss_mb = rss1 / 1024
    ok = cpu_pct < CPU_MAX_PCT and rss1 < RSS_MAX_KB
    print(
        f"CPU: {cpu_pct:.1f} % (budget < {CPU_MAX_PCT} %) | "
        f"RSS: {rss_mb:.1f} Mo (budget < {RSS_MAX_KB / 1024:.0f} Mo)"
    )
    print(f"État du budget M9: {'CONFORME' if ok else 'NON-CONFORME'}")
    return 0 if ok else 2


def cmd_prune(args: argparse.Namespace) -> int:
    """Supprimer les exemplaires audio orphelins (cluster absent de la base)."""
    config = load_config(args.config)
    store = EventStore(
        db_path=config.storage.db_path,
        batch_size=config.storage.batch_size,
    )
    removed = store.prune_orphaned_exemplars(config.storage.exemplars_dir)
    print(f"Exemplaires orphelins supprimés : {removed}")
    store.close()
    return 0


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="bruittrack",
        description="BruitTrack - Traqueur de bruits récurrents et infrasons 24/7",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", "-c", type=str, default=None, help="Chemin du fichier config.toml")

    subparsers = parser.add_subparsers(dest="command", help="Sous-commandes")

    # devices
    subparsers.add_parser("devices", help="Lister les périphériques audio d'entrée")

    # test
    test_p = subparsers.add_parser("test", help="Test live en terminal sans GUI")
    test_p.add_argument("--seconds", "-s", type=int, default=30, help="Durée du test en secondes (défaut: 30)")
    test_p.add_argument("--synthetic", action="store_true", help="Utiliser un signal de test synthétique")
    test_p.add_argument("--verbose-floor", dest="verbose_floor", action="store_true",
                        help="Imprimer l'état du FloorTracker (chaud, médiane) toutes les 10 s")

    # start
    subparsers.add_parser("start", help="Démarrer le démon de capture et détection")

    # viz
    viz_p = subparsers.add_parser("viz", help="Démarrer le serveur web de visualisation")
    viz_p.add_argument("--port", "-p", type=int, default=None, help="Port d'écoute (défaut: 8760)")
    viz_p.add_argument("--host", type=str, default=None, help="Adresse d'écoute (défaut: 0.0.0.0)")

    # stats
    stats_p = subparsers.add_parser("stats", help="Afficher les statistiques de la base")
    stats_p.add_argument("--play", type=int, default=None, help="Rejouer l'extrait audio d'un cluster")
    stats_p.add_argument("--json", action="store_true", help="Sortie JSON machine (conforme matrice de vérification M6)")

    # perf
    perf_p = subparsers.add_parser(
        "perf", help=f"Vérifier le budget CPU/RSS d'un PID sur {PERF_SAMPLE_SECONDS} s (matrice M9)"
    )
    perf_p.add_argument("--pid", type=int, default=None,
                        help="PID à mesurer (défaut: le processus courant)")

    # prune
    subparsers.add_parser(
        "prune",
        help="Supprimer les exemplaires audio orphelins (cluster non présent en base)",
    )

    args = parser.parse_args()

    if args.command == "devices":
        return cmd_devices(args)
    elif args.command == "test":
        return cmd_test(args)
    elif args.command == "start":
        return cmd_start(args)
    elif args.command == "viz":
        return cmd_viz(args)
    elif args.command == "stats":
        return cmd_stats(args)
    elif args.command == "perf":
        return cmd_perf(args)
    elif args.command == "prune":
        return cmd_prune(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
