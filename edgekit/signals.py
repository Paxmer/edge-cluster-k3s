"""Simulador de señales de un motor con rodamiento: temperatura + vibración.

IMPORTANTE: los datos son SINTÉTICOS. Se generan con un modelo físico simple:
un defecto en la pista externa del rodamiento produce impulsos periódicos a la
frecuencia BPFO que excitan una resonancia estructural (~300 Hz). A mayor
severidad, más amplitud de impulsos, más ruido y más temperatura.
"""
import numpy as np

FS = 1024                    # Hz, frecuencia de muestreo del acelerómetro simulado
WINDOW = 256                 # muestras por lectura (0.25 s)
SHAFT_HZ = 25.0              # giro del eje (1500 rpm)
BPFO_HZ = 3.58 * SHAFT_HZ    # frecuencia de falla de la pista externa (~89.5 Hz)
RESONANCE_HZ = 300.0         # resonancia excitada por los impulsos

CLASSES = ["normal", "desgaste", "falla_inminente"]

# Rango de severidad (0 = sano, 1 = falla total) que define cada clase.
# La etiqueta depende solo de la severidad real; el modelo ve señales con ruido,
# así que se equivoca sobre todo cerca de las fronteras (0.25 y 0.65).
SEVERITY_RANGES = {
    "normal": (0.0, 0.25),
    "desgaste": (0.25, 0.65),
    "falla_inminente": (0.65, 1.0),
}

_KERNEL_N = 48
_n = np.arange(_KERNEL_N)
_KERNEL = np.exp(-_n / 9.0) * np.sin(2 * np.pi * RESONANCE_HZ * _n / FS)


def generate_window(rng, severity):
    """Devuelve (temperatura_c, vibracion[WINDOW]) para una severidad dada."""
    t = np.arange(WINDOW) / FS
    phase = rng.uniform(0, 2 * np.pi)
    shaft = rng.normal(0.5, 0.08) * np.sin(2 * np.pi * SHAFT_HZ * t + phase)
    noise = rng.normal(0.0, 0.30 * (1 + 0.8 * severity), WINDOW)
    x = shaft + noise

    if severity > 0:
        period = FS / BPFO_HZ
        pos = rng.uniform(0, period)
        impulses = np.zeros(WINDOW + _KERNEL_N)
        while pos < WINDOW:
            impulses[int(pos)] += 2.5 * severity * rng.lognormal(0, 0.25)
            pos += period * rng.normal(1.0, 0.01)   # pequeño deslizamiento
        x = x + np.convolve(impulses, _KERNEL)[:WINDOW]

    temperature = 45.0 + rng.normal(0, 3.0) + 35.0 * severity ** 1.2 + rng.normal(0, 1.5)
    return float(temperature), x


def make_window_for_class(rng, class_name):
    lo, hi = SEVERITY_RANGES[class_name]
    return generate_window(rng, rng.uniform(lo, hi))
