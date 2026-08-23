"""Publier (ou vérifier) la release GitHub du tag local.

Usage :
    python scripts/creer_release.py --repo OWNER/nom-repo

Le token est lu dans GITHUB_TOKEN. L'opération est idempotente : si une
release existe déjà pour le tag, aucune écriture n'est effectuée.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request

API = "https://api.github.com"

DEFAULT_NOTES = """## BruitTrack v1.0.0

- CI : CPython 3.11, 3.12, 3.13 (ruff + pytest).
- Contraintes HP T620 (fanless) : CPU < 15 %, RAM < 150 Mo, pipeline
  numpy/scipy sans dump PCM, SQLite WAL en lots de 30 s.
- Purge des événements à fréquence nulle :
  `sqlite3 data/bruittrack.db \\"-\\" < scripts/purge_noise.sql`
- Déploiement systemd : `systemctl restart bruittrack` (cf. `systemd/bruittrack.service`).
"""


def _request(method: str, url: str, token: str, body: dict | None = None) -> tuple[int, str]:
    """Appel GitHub API ; retourne (statut HTTP, texte brut)."""
    data = json.dumps(body).encode() if body else None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "bruittrack-release",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def main() -> int:
    p = argparse.ArgumentParser(description="Publier la release GitHub du tag")
    p.add_argument("--repo", required=True, help="owner/nom-repo distant")
    p.add_argument("--tag", default="v1.0.0", help="Tag à publier (défaut v1.0.0)")
    p.add_argument("--notes", default=DEFAULT_NOTES, help="Notes de release (markdown)")
    args = p.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("ERREUR : GITHUB_TOKEN absent dans l'environnement.")
        return 2

    status, raw = _request("GET", f"{API}/repos/{args.repo}/releases/tags/{args.tag}", token)
    if status == 200:
        print(f"Release {args.tag} déjà publiée : {json.loads(raw).get('html_url', '')}")
        return 0
    if status != 404:
        print(f"ERREUR GET (HTTP {status}) : {raw[:300]}")
        return 1

    status, raw = _request(
        "POST",
        f"{API}/repos/{args.repo}/releases",
        token,
        body={
            "tag_name": args.tag,
            "name": args.tag,
            "target_commitish": args.tag,
            "body": args.notes,
        },
    )
    if status in (200, 201):
        print(f"OK : release {args.tag} publiée → {json.loads(raw).get('html_url', '')}")
        return 0
    print(f"ERREUR POST (HTTP {status}) : {raw[:300]}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
