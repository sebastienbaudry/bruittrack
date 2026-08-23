- Environnement de dev local (Windows/Python 3.14) sans `ruff` installé : le lint
  sera validé sur la cible Debian / CI avant merge.

## A016 (iteration 43)
pi-t620: PortAudio `sd.query_devices()` reports **max_input_channels=0** for M-Track Plus (`M-Audio M-Track Plus at usb-...`, card 2, hw:2,0) even though `/proc/asound/pcm` shows `02-00: USB Audio : capture 1` and the **running bruittrack service (PID 27534, uptime 8h45m) is producing real events (514 total / 303 clusters)** via exactly this card. Assumption: PortAudio's device-info path fails to enumerate the USB capture substream on this kernel/full-speed combo, but the actual `sd.InputStream(device="M-Track Plus" or ALSA string)` open **does work** in-process (proven by live service). Consequence: standalone probes via sounddevice show 0ch; functional proof of capture = the live service + `bruittrack test --synthetic` rc=0.
A017: replay sox non auditionné (pi-t620 headless, pas de sortie audio praticable à distance)

## A018 — Layout réel pi-t620 (it.77-79)
Le dépôt déployé est PLAT : /opt/bruittrack contient src/, tools/, .venv/ (pas de dossier git/). Le script local de référence vise ${APP_DIR}/git/.venv ; le fallback [ -x ] || PYB=${APP_DIR}/.venv/bin/python rend la smoke M9 correcte sur les deux layouts. Preuve it.79 : PYB résolue /opt/bruittrack/.venv/bin/python, MAIN=27534, perf → CONFORME RC=0 (12.8 % / 123.5 Mo).
- Conformite legale : bit3 (FLAG_OVER_LEGAL) pose si l event depasse la limite CSP R1336-7 evaluee avec duree_cumulee approximee par la duree de l event et l heure locale du t0.
