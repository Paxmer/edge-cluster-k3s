"""Cliente HTTP con reintento hacia varios nodos (usa solo la biblioteca estándar).

Sirve para el simulador de sensores y para la prueba de caída de un worker:
si un nodo no responde, el cliente prueba el siguiente endpoint de la lista.
"""
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field


@dataclass
class Result:
    ok: bool
    first_try_ok: bool
    attempts: int
    latency_ms: float
    endpoint: str = ""
    data: dict = field(default_factory=dict)
    error: str = ""


def post_json(url, payload, timeout):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


class FailoverClient:
    def __init__(self, endpoints, timeout=0.8, max_attempts=3, sticky=False):
        self.endpoints = [e.rstrip("/") for e in endpoints]
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.sticky = sticky
        self._i = 0

    def predict(self, payload):
        t0 = time.monotonic()
        last_error = ""
        n = len(self.endpoints)
        for k in range(self.max_attempts):
            ep = self.endpoints[(self._i + k) % n]
            try:
                data = post_json(ep + "/predict", payload, self.timeout)
            except urllib.error.HTTPError as e:
                last_error = f"HTTP {e.code}"
                if e.code < 500:      # error del cliente: reintentar no sirve
                    break
                continue
            except Exception as e:     # timeout, conexión rechazada, nodo caído...
                last_error = type(e).__name__
                continue
            if not self.sticky:
                self._i = (self._i + 1) % n          # reparte entre nodos
            else:
                self._i = (self._i + k) % n          # se queda en el último que funcionó
            return Result(True, k == 0, k + 1, (time.monotonic() - t0) * 1000, ep, data)
        if not self.sticky:
            self._i = (self._i + 1) % n
        return Result(False, False, self.max_attempts, (time.monotonic() - t0) * 1000, "", {}, last_error)
