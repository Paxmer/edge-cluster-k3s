#!/usr/bin/env python3
"""Prueba de tolerancia a fallos: carga constante mientras se apaga un worker.

Uso:
  python failover_test.py --endpoints http://192.168.100.11:30080,http://192.168.100.12:30080 \\
      --rate 5 --duration 120 --csv resultados.csv --plot resultados.png

Pasos durante la prueba (ver README):
  1. Deja correr ~30 s con los dos workers vivos (línea base).
  2. Apaga o desconecta un worker (sudo poweroff, o quita el cable de red).
  3. Deja correr hasta el final y, si quieres, vuelve a encenderlo.

El script registra cada petición y al final imprime: éxito al primer intento
(sin ayuda del cliente), éxito final (con reintento hacia otro nodo), latencias,
la ventana más larga sin respuestas y el reparto de peticiones por nodo y pod.
"""
import argparse
import csv
import statistics
import time

import numpy as np

from edgekit.client import FailoverClient
from edgekit.signals import CLASSES, make_window_for_class


def build_pool(seed, size=60):
    rng = np.random.default_rng(seed)
    pool = []
    for i in range(size):
        temp, vib = make_window_for_class(rng, CLASSES[i % len(CLASSES)])
        pool.append({"temperature_c": round(temp, 2), "vibration": [round(float(v), 4) for v in vib]})
    return pool


def percentile(values, p):
    if not values:
        return float("nan")
    s = sorted(values)
    return s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))]


def summarize_after_cut(rows, rate, cut_at=None):
    """Métricas solo del tramo posterior al corte.

    El resumen global se diluye con las peticiones previas al corte (todas correctas) y con el hecho de
    que, tras la caída, el cliente espera hasta varios segundos por petición fallida y envía menos
    peticiones de las 'rate' por segundo. Por eso se reporta aparte lo ocurrido después del corte.
    Si no se indica cut_at, se toma el instante de la primera petición que falló al primer intento.
    """
    if cut_at is None:
        first_bad = [r["t_s"] for r in rows if not r["ok_primer_intento"]]
        if not first_bad:
            return None
        cut_at = first_bad[0]
    post = [r for r in rows if r["t_s"] >= cut_at]
    if not post:
        return None
    span = max(1e-9, rows[-1]["t_s"] - cut_at + 1.0 / rate)
    lat = [r["latencia_ms"] for r in post if r["ok"]]
    return {
        "corte_s": round(cut_at, 1), "peticiones": len(post),
        "exito_final": sum(r["ok"] for r in post), "exito_primer_intento": sum(r["ok_primer_intento"] for r in post),
        "respuestas_ok_por_s": round(sum(r["ok"] for r in post) / span, 2),
        "peticiones_enviadas_por_s": round(len(post) / span, 2),
        "mediana_ms": round(statistics.median(lat), 1) if lat else float("nan"),
        "p95_ms": round(percentile(lat, 95), 1) if lat else float("nan"),
    }


def print_after_cut(rows, rate, cut_at=None):
    d = summarize_after_cut(rows, rate, cut_at)
    if not d:
        print("\nTramo posterior al corte: no se detectaron fallos al primer intento.")
        return
    n = d["peticiones"]
    print(f"\n=== SOLO DESPUES DEL CORTE (desde t = {d['corte_s']} s) ===")
    print(f"Peticiones:                    {n} ({d['peticiones_enviadas_por_s']} por segundo; objetivo {rate:g})")
    print(f"Exito final (con reintento):   {d['exito_final']}/{n} = {100 * d['exito_final'] / n:.2f} %")
    print(f"Exito al primer intento:       {d['exito_primer_intento']}/{n} = {100 * d['exito_primer_intento'] / n:.2f} %")
    print(f"Respuestas correctas por seg.: {d['respuestas_ok_por_s']}")
    print(f"Latencia (ok) mediana / p95:   {d['mediana_ms']} ms / {d['p95_ms']} ms")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoints", required=True, help="URLs separadas por coma (una por nodo)")
    ap.add_argument("--rate", type=float, default=5.0, help="peticiones por segundo")
    ap.add_argument("--duration", type=float, default=120.0, help="segundos de prueba")
    ap.add_argument("--timeout", type=float, default=0.8, help="timeout por intento (s)")
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--sticky", action="store_true", help="no rotar entre nodos")
    ap.add_argument("--cut-at", type=float, default=None, help="segundo en que se cortó el worker (si no, se detecta solo)")
    ap.add_argument("--csv", default="resultados_failover.csv")
    ap.add_argument("--plot", default="", help="ruta del PNG (requiere matplotlib)")
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()

    client = FailoverClient(args.endpoints.split(","), timeout=args.timeout,
                            max_attempts=args.max_attempts, sticky=args.sticky)
    pool = build_pool(args.seed)
    period = 1.0 / args.rate
    rows = []
    start = time.monotonic()
    i = 0
    print(f"Enviando {args.rate:g} peticiones/s durante {args.duration:g} s... (apaga un worker cuando quieras)")
    while True:
        t_send = time.monotonic() - start
        if t_send >= args.duration:
            break
        res = client.predict(pool[i % len(pool)])
        i += 1
        rows.append({
            "t_s": round(t_send, 3), "ok": int(res.ok), "ok_primer_intento": int(res.first_try_ok),
            "intentos": res.attempts, "latencia_ms": round(res.latency_ms, 2),
            "nodo": res.data.get("node", ""), "pod": res.data.get("pod", ""),
            "endpoint": res.endpoint, "error": res.error,
        })
        if i % int(max(1, args.rate * 5)) == 0:
            ok_rec = sum(r["ok"] for r in rows[-int(args.rate * 5):])
            print(f"  t={t_send:6.1f}s  ultimas {min(len(rows), int(args.rate * 5))} peticiones: {ok_rec} ok")
        time.sleep(max(0.0, (start + i * period) - time.monotonic()))

    with open(args.csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    total = len(rows)
    ok = sum(r["ok"] for r in rows)
    ok1 = sum(r["ok_primer_intento"] for r in rows)
    lat_ok = [r["latencia_ms"] for r in rows if r["ok"]]

    # ventana más larga sin ninguna respuesta correcta
    longest, run_start = 0.0, None
    for r in rows:
        if not r["ok"]:
            run_start = r["t_s"] if run_start is None else run_start
            longest = max(longest, r["t_s"] - run_start + 1.0 / args.rate)
        else:
            run_start = None

    by_node, by_pod = {}, {}
    for r in rows:
        if r["ok"]:
            by_node[r["nodo"]] = by_node.get(r["nodo"], 0) + 1
            by_pod[r["pod"]] = by_pod.get(r["pod"], 0) + 1

    print("\n=== RESUMEN ===")
    print(f"Peticiones totales:            {total}")
    print(f"Exito final (con reintento):   {ok}/{total} = {100 * ok / total:.2f} %")
    print(f"Exito al primer intento:       {ok1}/{total} = {100 * ok1 / total:.2f} %")
    print(f"Latencia (ok) mediana / p95:   {statistics.median(lat_ok) if lat_ok else float('nan'):.1f} ms / {percentile(lat_ok, 95):.1f} ms")
    print(f"Ventana mas larga sin servicio: {longest:.1f} s")
    print(f"Reparto por nodo: {by_node}")
    print(f"Reparto por pod:  {by_pod}")
    print_after_cut(rows, args.rate, args.cut_at)
    print(f"CSV guardado en {args.csv}")

    if args.plot:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            print("matplotlib no esta instalado: se omite la grafica.")
            return
        fig, ax = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
        t_ok = [r["t_s"] for r in rows if r["ok"]]
        ax[0].scatter(t_ok, lat_ok, s=8, color="#2b8a3e", label="respuesta correcta")
        t_bad = [r["t_s"] for r in rows if not r["ok"]]
        ax[0].scatter(t_bad, [max(lat_ok + [100]) * 1.05] * len(t_bad), s=30, marker="x", color="#c92a2a", label="sin respuesta")
        ax[0].set_ylabel("Latencia (ms)")
        ax[0].legend(loc="upper right")
        ax[0].set_title("Prueba de caída de un worker")
        for node in sorted(by_node):
            ts = [r["t_s"] for r in rows if r["ok"] and r["nodo"] == node]
            ax[1].step(ts, range(1, len(ts) + 1), where="post", label=node)
        ax[1].set_ylabel("Respuestas acumuladas")
        ax[1].set_xlabel("Tiempo (s)")
        ax[1].legend(loc="upper left")
        fig.tight_layout()
        fig.savefig(args.plot, dpi=150)
        print(f"Grafica guardada en {args.plot}")


if __name__ == "__main__":
    main()
