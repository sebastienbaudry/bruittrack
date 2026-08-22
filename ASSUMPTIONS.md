- Environnement de dev local (Windows/Python 3.14) sans `ruff` installé : le lint
  sera validé sur la cible Debian / CI avant merge.

## A016 (iteration 43)
pi-t620: PortAudio `sd.query_devices()` reports **max_input_channels=0** for M-Track Plus (`M-Audio M-Track Plus at usb-...`, card 2, hw:2,0) even though `/proc/asound/pcm` shows `02-00: USB Audio : capture 1` and the **running bruittrack service (PID 27534, uptime 8h45m) is producing real events (514 total / 303 clusters)** via exactly this card. Assumption: PortAudio's device-info path fails to enumerate the USB capture substream on this kernel/full-speed combo, but the actual `sd.InputStream(device="M-Track Plus" or ALSA string)` open **does work** in-process (proven by live service). Consequence: standalone probes via sounddevice show 0ch; functional proof of capture = the live service + `bruittrack test --synthetic` rc=0.
