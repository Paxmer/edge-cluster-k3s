#!/usr/bin/env python3
"""Servicio de inferencia de mantenimiento predictivo.

Usa solo la biblioteca estándar de Python + numpy/scikit-learn (sin FastAPI):
imagen más pequeña y menos RAM en los nodos pequeños.

Endpoints:
  POST /predict  {"temperature_c": 62.5, "vibration": [256 números]}
  GET  /health   liveness (el proceso responde)
  GET  /ready    readiness (el modelo está cargado)
  GET  /info     pod, nodo, modelo, versión
  GET  /metrics  métricas en formato Prometheus

Variables de entorno: MODEL_PATH, PORT, NODE_NAME, POD_NAME.
"""
import json
import math
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import joblib
import numpy as np

from edgekit import __version__
from edgekit.features import extract_features
from edgekit.signals import WINDOW

MODEL_PATH = os.environ.get("MODEL_PATH", "artifacts/model.joblib")
PORT = int(os.environ.get("PORT", "8000"))
NODE = os.environ.get("NODE_NAME", "desconocido")
POD = os.environ.get("POD_NAME", os.environ.get("HOSTNAME", "local"))
MAX_BODY = 64 * 1024
BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)
START = time.time()

BUNDLE = None  # se carga en main()


class Metrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.requests = {}      # (endpoint, status) -> contador
        self.predictions = {}   # etiqueta -> contador
        self.bucket_counts = [0] * len(BUCKETS)
        self.latency_sum = 0.0
        self.latency_count = 0

    def request(self, endpoint, status):
        with self.lock:
            key = (endpoint, str(status))
            self.requests[key] = self.requests.get(key, 0) + 1

    def prediction(self, label, seconds):
        with self.lock:
            self.predictions[label] = self.predictions.get(label, 0) + 1
            self.latency_sum += seconds
            self.latency_count += 1
            for i, b in enumerate(BUCKETS):
                if seconds <= b:
                    self.bucket_counts[i] += 1
                    break

    def render(self):
        lab = f'pod="{POD}",node="{NODE}"'
        out = [
            "# HELP edge_up El servicio esta en marcha.", "# TYPE edge_up gauge", f"edge_up{{{lab}}} 1",
            "# HELP edge_start_time_seconds Inicio del proceso (epoch).", "# TYPE edge_start_time_seconds gauge",
            f"edge_start_time_seconds{{{lab}}} {START:.0f}",
            "# HELP edge_requests_total Peticiones HTTP atendidas.", "# TYPE edge_requests_total counter",
        ]
        with self.lock:
            for (ep, st), n in sorted(self.requests.items()):
                out.append(f'edge_requests_total{{{lab},endpoint="{ep}",status="{st}"}} {n}')
            out += ["# HELP edge_predictions_total Predicciones por clase.", "# TYPE edge_predictions_total counter"]
            for label, n in sorted(self.predictions.items()):
                out.append(f'edge_predictions_total{{{lab},label="{label}"}} {n}')
            out += ["# HELP edge_request_duration_seconds Latencia de /predict (inferencia).",
                    "# TYPE edge_request_duration_seconds histogram"]
            acc = 0
            for b, c in zip(BUCKETS, self.bucket_counts):
                acc += c
                out.append(f'edge_request_duration_seconds_bucket{{{lab},le="{b}"}} {acc}')
            out.append(f'edge_request_duration_seconds_bucket{{{lab},le="+Inf"}} {self.latency_count}')
            out.append(f"edge_request_duration_seconds_sum{{{lab}}} {self.latency_sum:.6f}")
            out.append(f"edge_request_duration_seconds_count{{{lab}}} {self.latency_count}")
        return ("\n".join(out) + "\n").encode()


METRICS = Metrics()


def validate(payload):
    """Devuelve un mensaje de error o None si el JSON es válido."""
    if not isinstance(payload, dict):
        return "el cuerpo debe ser un objeto JSON"
    temp = payload.get("temperature_c")
    if isinstance(temp, bool) or not isinstance(temp, (int, float)) or not math.isfinite(temp):
        return "temperature_c debe ser un numero"
    if not -50 <= temp <= 250:
        return "temperature_c fuera de rango (-50 a 250)"
    vib = payload.get("vibration")
    if not isinstance(vib, list) or len(vib) != WINDOW:
        return f"vibration debe ser una lista de {WINDOW} numeros"
    for v in vib:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            return "vibration contiene valores no numericos o infinitos"
    return None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "edge-infer/" + __version__

    def log_message(self, fmt, *args):  # sin ruido en consola
        pass

    def _send(self, status, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/health":
            status, body = 200, {"status": "ok"}
        elif path == "/ready":
            ok = BUNDLE is not None
            status, body = (200, {"status": "ready"}) if ok else (503, {"status": "loading"})
        elif path == "/info":
            status, body = 200, {"pod": POD, "node": NODE, "version": __version__,
                                 "model": BUNDLE["model_name"], "classes": BUNDLE["classes"],
                                 "uptime_s": round(time.time() - START, 1)}
        elif path == "/metrics":
            METRICS.request(path, 200)
            return self._send(200, METRICS.render(), "text/plain; version=0.0.4")
        else:
            status, body = 404, {"error": "ruta no encontrada"}
        METRICS.request(path if status != 404 else "otro", status)
        self._send(status, body)

    def do_POST(self):
        if self.path.split("?")[0] != "/predict":
            METRICS.request("otro", 404)
            return self._send(404, {"error": "ruta no encontrada"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            METRICS.request("/predict", 400)
            return self._send(400, {"error": "cuerpo vacio o demasiado grande"})
        try:
            payload = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError):
            METRICS.request("/predict", 400)
            return self._send(400, {"error": "JSON invalido"})
        error = validate(payload)
        if error:
            METRICS.request("/predict", 400)
            return self._send(400, {"error": error})

        t0 = time.perf_counter()
        feats = extract_features(payload["temperature_c"], payload["vibration"])
        proba = BUNDLE["model"].predict_proba(feats.reshape(1, -1))[0]
        idx = int(np.argmax(proba))
        label = BUNDLE["classes"][idx]
        seconds = time.perf_counter() - t0
        METRICS.prediction(label, seconds)
        METRICS.request("/predict", 200)
        self._send(200, {
            "label": label,
            "alerta": label != "normal",
            "probabilities": {c: round(float(p), 4) for c, p in zip(BUNDLE["classes"], proba)},
            "latency_ms": round(seconds * 1000, 3),
            "pod": POD, "node": NODE,
        })


def make_server(port=PORT):
    return ThreadingHTTPServer(("0.0.0.0", port), Handler)


def load_bundle(path=MODEL_PATH):
    global BUNDLE
    BUNDLE = joblib.load(path)
    return BUNDLE


def main():
    try:
        load_bundle()
    except Exception as e:
        print(f"No se pudo cargar el modelo en {MODEL_PATH}: {e}", file=sys.stderr)
        sys.exit(1)
    server = make_server()
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown).start())
    print(f"edge-infer {__version__} | modelo={BUNDLE['model_name']} | pod={POD} nodo={NODE} | puerto {PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()


if __name__ == "__main__":
    main()
