#!/usr/bin/env python3
"""Analiza un CSV de failover_test.py y muestra las métricas del tramo posterior al corte.

Uso:  python analizar_csv.py resultados_failover.csv [--rate 5] [--cut-at 30]
"""
import argparse
import csv

from failover_test import print_after_cut


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--rate", type=float, default=5.0)
    ap.add_argument("--cut-at", type=float, default=None)
    a = ap.parse_args()
    with open(a.csv, newline="") as f:
        rows = [{"t_s": float(r["t_s"]), "ok": int(r["ok"]), "ok_primer_intento": int(r["ok_primer_intento"]),
                 "latencia_ms": float(r["latencia_ms"])} for r in csv.DictReader(f)]
    print(f"{len(rows)} peticiones en total")
    print_after_cut(rows, a.rate, a.cut_at)


if __name__ == "__main__":
    main()
