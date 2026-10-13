"""Extracción de características de una lectura (temperatura + ventana de vibración)."""
import numpy as np

from .signals import FS

FEATURE_NAMES = [
    "temperatura_c", "rms", "pico", "factor_cresta", "curtosis",
    "energia_0_60hz", "energia_60_150hz", "energia_150_300hz", "energia_300_512hz",
]
BANDS = [(0, 60), (60, 150), (150, 300), (300, 512.01)]


def extract_features(temperature_c, vibration, fs=FS):
    x = np.asarray(vibration, dtype=float)
    x = x - x.mean()
    rms = float(np.sqrt(np.mean(x ** 2)))
    peak = float(np.max(np.abs(x)))
    crest = peak / rms if rms > 0 else 0.0
    var = float(np.var(x))
    kurt = float(np.mean(x ** 4) / var ** 2) if var > 0 else 0.0

    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) / len(x)
    freqs = np.fft.rfftfreq(len(x), 1.0 / fs)
    energies = [float(np.sum(spec[(freqs >= lo) & (freqs < hi)] ** 2)) for lo, hi in BANDS]

    return np.array([float(temperature_c), rms, peak, crest, kurt, *energies])
