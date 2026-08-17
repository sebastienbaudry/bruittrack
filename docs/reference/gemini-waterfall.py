import numpy as np
import scipy.signal as signal
import sounddevice as sd
import matplotlib
matplotlib.use('TkAgg')  # Backend interactif imposé explicitement (nécessite python3-tk)
import matplotlib.pyplot as plt
import queue
import time

# --- CONFIGURATION ---
ID_MAUDIO = None        # None = périphérique d'enregistrement par défaut du système
FS_ORIG = 44100
DECIMATION = 44         # Fréquence basse = 1002.27 Hz
FS_LOW = FS_ORIG / DECIMATION

BLOCK_SIZE = 4400       # ~0.1s par bloc
N_BUFFER = 8192         # Taille du buffer glissant (~8.17 s d'historique audio)

# Paramètres du moyennage de Welch
N_SEG = 2048            # Taille des sous-segments (2048 => rés. ~0.489 Hz/bin, 7 segments moyennés)
NOVERLAP = N_SEG // 2   # Recouvrement à 50% pour optimiser le lissage statistique

FREQ_MAX = 48.0         
HISTORY_LEN = 300       
FPS_TARGET = 15         

# File d'attente thread-safe
raw_audio_queue = queue.Queue()

# Variable de contrôle pour la boucle principale
running = True

def on_close(event):
    """Callback appelé lors de la fermeture de la fenêtre Tkinter/Matplotlib."""
    global running
    running = False

# Filtre anti-repliement (coupure 400 Hz)
sos = signal.cheby1(8, 0.05, 400 / (FS_ORIG / 2), output='sos')
zi_init_state = signal.sosfilt_zi(sos)
zi_init_state = np.repeat(zi_init_state[:, np.newaxis, :], 2, axis=1)

# Fréquences basées sur la taille des sous-segments de Welch (N_SEG)
freqs_low = np.fft.rfftfreq(N_SEG, 1 / FS_LOW)
mask = freqs_low <= FREQ_MAX
f_sub = freqs_low[mask]

def compute_welch_db(buf):
    """Calcule le spectre moyen par la méthode de Welch sur les 2 canaux simultanément."""
    _, psd = signal.welch(buf, fs=FS_LOW, window='hann', 
                          nperseg=N_SEG, noverlap=NOVERLAP, 
                          axis=0, scaling='spectrum')
    # psd a pour forme (N_SEG//2 + 1, 2)
    db1 = 10 * np.log10(psd[mask, 0] + 1e-12)
    db2 = 10 * np.log10(psd[mask, 1] + 1e-12)
    return db1, db2

# --- CAPTURE INITIALE ---
print("Pré-remplissage du buffer audio (capture de ~8 secondes)...")
try:
    with sd.InputStream(device=ID_MAUDIO, channels=2, samplerate=FS_ORIG, latency='high') as stream:
        raw_init, _ = stream.read(N_BUFFER * DECIMATION)
except Exception as e:
    print(f"Erreur à l'ouverture du périphérique audio (ID={ID_MAUDIO}) : {e}")
    print("Vérifiez l'ID avec sd.query_devices() et corrigez ID_MAUDIO en conséquence.")
    raise SystemExit(1)

zi = zi_init_state * raw_init[0, :].reshape(1, 2, 1)
filtered_init, zi = signal.sosfilt(sos, raw_init, zi=zi, axis=0)
audio_buffer_low = filtered_init[::DECIMATION, :]

db1_init, db2_init = compute_welch_db(audio_buffer_low)

waterfall1 = np.tile(db1_init[:, np.newaxis], (1, HISTORY_LEN))
waterfall2 = np.tile(db2_init[:, np.newaxis], (1, HISTORY_LEN))

# Référence de calibration (bruit de fond par bin de fréquence)
floor_ref1 = db1_init.copy()
floor_ref2 = db2_init.copy()

# Lissage temporel inter-blocs (EMA)
EMA_ALPHA = 0.5          # 0 = lissage maximal, 1 = pas de lissage
psd_db1_smooth = db1_init.copy()
psd_db2_smooth = db2_init.copy()

# Contraste couleur auto-ajusté (percentiles) sur l'écart au calibrage
PCTL_LOW, PCTL_HIGH = 5, 99.5
MIN_DYNAMIC_RANGE_DB = 10   

# --- CALLBACK AUDIO ---
def audio_callback(indata, frames, time_info, status):
    if status:
        print(f"[Audio] Statut : {status}")
    if running:
        raw_audio_queue.put_nowait(indata.copy())

def on_key(event):
    """Recalibre le plancher de bruit sur les ~5 dernières secondes (touche 'c')."""
    global floor_ref1, floor_ref2
    if event.key == 'c':
        floor_ref1 = np.median(waterfall1[:, -50:], axis=1)
        floor_ref2 = np.median(waterfall2[:, -50:], axis=1)
        print("Recalibration du bruit de fond effectuée.")

# --- GRAPHISME ---
plt.ion()
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 9), sharex=True)
fig.canvas.mpl_connect('close_event', on_close)
fig.canvas.mpl_connect('key_press_event', on_key)

res_hz = FS_LOW / N_SEG
fig.suptitle(f"Waterfall Infrasons (0-{FREQ_MAX} Hz) | Welch N={N_SEG} ({res_hz:.3f} Hz/bin) | Touche 'c' = recalibrer", 
             fontsize=13, fontweight='bold')

extent_args = [0, HISTORY_LEN, f_sub[0], f_sub[-1]]

rel1_init = waterfall1 - floor_ref1[:, np.newaxis]
rel2_init = waterfall2 - floor_ref2[:, np.newaxis]

im1 = ax1.imshow(rel1_init, aspect='auto', origin='lower', cmap='inferno',
                 extent=extent_args, vmin=0, vmax=15, interpolation='nearest')
im2 = ax2.imshow(rel2_init, aspect='auto', origin='lower', cmap='inferno',
                 extent=extent_args, vmin=0, vmax=15, interpolation='nearest')

ax1.set_title("Canal 1 (M-Track IN 1)")
ax1.set_ylabel("Fréquence (Hz)")
cb1 = fig.colorbar(im1, ax=ax1, label="Écart au calibrage (dB)")

ax2.set_title("Canal 2 (M-Track IN 2 - Piézo)")
ax2.set_ylabel("Fréquence (Hz)")
ax2.set_xlabel("Défilement temporel (Blocs)")
cb2 = fig.colorbar(im2, ax=ax2, label="Écart au calibrage (dB)")

plt.tight_layout()
print("Affichage actif. Touche 'c' = recalibrer le bruit de fond. Fermez la fenêtre ou Ctrl+C pour quitter.")

# --- BOUCLE PRINCIPALE ---
last_draw_time = time.time()
frame_interval = 1.0 / FPS_TARGET

try:
    with sd.InputStream(device=ID_MAUDIO, channels=2, samplerate=FS_ORIG, 
                        blocksize=BLOCK_SIZE, latency='high', callback=audio_callback):
        
        while running and plt.fignum_exists(fig.number):
            has_new_data = False
            
            # Dépilement et calculs audio
            while not raw_audio_queue.empty():
                try:
                    data = raw_audio_queue.get_nowait()
                except queue.Empty:
                    break
                
                filtered_data, zi = signal.sosfilt(sos, data, zi=zi, axis=0)
                data_low = filtered_data[::DECIMATION, :]
                n_samples_low = data_low.shape[0]
                
                audio_buffer_low = np.roll(audio_buffer_low, -n_samples_low, axis=0)
                audio_buffer_low[-n_samples_low:, :] = data_low
                
                # Spectral averaging de Welch sur le buffer
                psd_db1, psd_db2 = compute_welch_db(audio_buffer_low)
                
                psd_db1_smooth = EMA_ALPHA * psd_db1 + (1 - EMA_ALPHA) * psd_db1_smooth
                psd_db2_smooth = EMA_ALPHA * psd_db2 + (1 - EMA_ALPHA) * psd_db2_smooth
                
                waterfall1 = np.roll(waterfall1, -1, axis=1)
                waterfall1[:, -1] = psd_db1_smooth
                
                waterfall2 = np.roll(waterfall2, -1, axis=1)
                waterfall2[:, -1] = psd_db2_smooth
                
                has_new_data = True

            # Rafraîchissement graphique régulé
            now = time.time()
            if has_new_data and (now - last_draw_time) >= frame_interval:
                if running and plt.fignum_exists(fig.number):
                    rel1 = waterfall1 - floor_ref1[:, np.newaxis]
                    rel2 = waterfall2 - floor_ref2[:, np.newaxis]
                    im1.set_data(rel1)
                    im2.set_data(rel2)

                    vmin1, vmax1 = np.percentile(rel1, [PCTL_LOW, PCTL_HIGH])
                    vmax1 = max(vmax1, vmin1 + MIN_DYNAMIC_RANGE_DB)
                    im1.set_clim(vmin1, vmax1)
                    cb1.update_normal(im1)

                    vmin2, vmax2 = np.percentile(rel2, [PCTL_LOW, PCTL_HIGH])
                    vmax2 = max(vmax2, vmin2 + MIN_DYNAMIC_RANGE_DB)
                    im2.set_clim(vmin2, vmax2)
                    cb2.update_normal(im2)

                    fig.canvas.draw_idle()
                    last_draw_time = now

            try:
                if running and plt.fignum_exists(fig.number):
                    fig.canvas.flush_events()
            except Exception:
                running = False
                break

            time.sleep(0.005)

except KeyboardInterrupt:
    print("\nArrêt du programme par l'utilisateur (Ctrl+C).")
except Exception as e:
    print(f"\nErreur : {e}")
finally:
    running = False
    plt.close('all')
    print("Programme fermé proprement.")