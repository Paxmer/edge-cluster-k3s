#!/usr/bin/env python3
"""Simulador de sensores: envía lecturas de temperatura y vibración al clúster.

Ejemplo (en la laptop conectada al switch):
  python simulator.py --endpoints http://192.168.100.11:30080,http://192.168.100.12:30080

La severidad de la máquina simulada sube poco a poco de 0 a 1 durante --duration
segundos, para ver cómo el modelo pasa de "normal" a "desgaste" y a "falla_inminente".
"""
import argparse
import time

import numpy as np

from edgekit.client import FailoverClient
from edgekit.signals import generate_window


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoints", required=True, help="URLs separadas por coma")
    ap.add_argument("--interval", type=float, default=1.0, help="segundos entre lecturas")
    ap.add_argument("--duration", type=float, default=60.0, help="segundos de simulación")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    client = FailoverClient(args.endpoints.split(","))
    rng = np.random.default_rng(args.seed)
    start = time.monotonic()
    n = 0
    print(f"{'t(s)':>6} {'sev.real':>8} {'temp(C)':>8}  {'prediccion':<16} {'nodo':<10} {'ms':>6}")
    while time.monotonic() - start < args.duration:
        t = time.monotonic() - start
        severity = min(1.0, t / args.duration)
        temp, vib = generate_window(rng, severity)
        res = client.predict({"temperature_c": round(temp, 2), "vibration": [round(float(v), 4) for v in vib]})
        n += 1
        if res.ok:
            d = res.data
            flag = "  <-- ALERTA" if d["alerta"] else ""
            print(f"{t:6.1f} {severity:8.2f} {temp:8.1f}  {d['label']:<16} {d['node']:<10} {res.latency_ms:6.1f}{flag}")
        else:
            print(f"{t:6.1f} {severity:8.2f} {temp:8.1f}  SIN RESPUESTA ({res.error})")
        time.sleep(max(0.0, args.interval - (time.monotonic() - start - t)))
    print(f"\n{n} lecturas enviadas.")


if __name__ == "__main__":
    main()
