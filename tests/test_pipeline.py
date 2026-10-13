"""Pruebas automáticas del kit. Ejecutar desde la raíz:  python -m unittest discover -s tests -v

Requieren haber entrenado antes (python train.py) para que exista artifacts/model.joblib.
"""
import json
import os
import threading
import unittest
import urllib.error
import urllib.request

import numpy as np

from edgekit.client import FailoverClient
from edgekit.features import FEATURE_NAMES, extract_features
from edgekit.signals import CLASSES, WINDOW, generate_window, make_window_for_class

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = os.path.join(ROOT, "artifacts", "model.joblib")


def payload(rng, class_name):
    temp, vib = make_window_for_class(rng, class_name)
    return {"temperature_c": round(temp, 2), "vibration": [round(float(v), 4) for v in vib]}


def post(url, body, raw=False):
    data = body if raw else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class SignalsAndFeatures(unittest.TestCase):
    def test_window_shape_and_temperature_grow_with_severity(self):
        rng = np.random.default_rng(0)
        t0, v0 = generate_window(rng, 0.0)
        t1, v1 = generate_window(rng, 1.0)
        self.assertEqual(len(v0), WINDOW)
        self.assertGreater(t1, t0)
        self.assertGreater(np.std(v1), np.std(v0))

    def test_features_length(self):
        rng = np.random.default_rng(1)
        temp, vib = generate_window(rng, 0.5)
        self.assertEqual(len(extract_features(temp, vib)), len(FEATURE_NAMES))


@unittest.skipUnless(os.path.exists(MODEL), "falta artifacts/model.joblib (ejecuta python train.py)")
class ServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["NODE_NAME"] = "nodo-test"
        from service import app
        app.load_bundle(MODEL)
        cls.app = app
        cls.servers = []
        cls.urls = []
        for _ in range(2):
            srv = app.make_server(0)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            cls.servers.append(srv)
            cls.urls.append(f"http://127.0.0.1:{srv.server_address[1]}")

    @classmethod
    def tearDownClass(cls):
        for s in cls.servers:
            try:
                s.shutdown()
            except Exception:
                pass
            s.server_close()

    def test_health_ready_info(self):
        for path in ("/health", "/ready", "/info"):
            with urllib.request.urlopen(self.urls[0] + path, timeout=5) as r:
                self.assertEqual(r.status, 200)

    def test_predict_valid_returns_known_label(self):
        rng = np.random.default_rng(3)
        status, body = post(self.urls[0] + "/predict", payload(rng, "falla_inminente"))
        self.assertEqual(status, 200)
        self.assertIn(body["label"], CLASSES)
        self.assertAlmostEqual(sum(body["probabilities"].values()), 1.0, places=2)

    def test_accuracy_on_fresh_simulated_data(self):
        rng = np.random.default_rng(99)
        correct = total = 0
        for name in CLASSES:
            for _ in range(60):
                status, body = post(self.urls[0] + "/predict", payload(rng, name))
                total += 1
                correct += int(status == 200 and body["label"] == name)
        self.assertGreater(correct / total, 0.85)

    def test_invalid_inputs_get_400(self):
        url = self.urls[0] + "/predict"
        rng = np.random.default_rng(5)
        good = payload(rng, "normal")
        bad_cases = [
            {"temperature_c": 50, "vibration": [0.1] * 10},                    # longitud incorrecta
            {"temperature_c": "caliente", "vibration": good["vibration"]},     # tipo incorrecto
            {"temperature_c": 900, "vibration": good["vibration"]},            # fuera de rango
            {"vibration": good["vibration"]},                                  # falta temperatura
            {"temperature_c": 50, "vibration": ["a"] * WINDOW},                # no numérico
        ]
        for case in bad_cases:
            status, body = post(url, case)
            self.assertEqual(status, 400, case)
            self.assertIn("error", body)
        status, _ = post(url, b"esto no es json", raw=True)
        self.assertEqual(status, 400)

    def test_metrics_exposed(self):
        rng = np.random.default_rng(6)
        post(self.urls[0] + "/predict", payload(rng, "normal"))
        with urllib.request.urlopen(self.urls[0] + "/metrics", timeout=5) as r:
            text = r.read().decode()
        self.assertIn("edge_requests_total", text)
        self.assertIn("edge_request_duration_seconds_bucket", text)
        self.assertIn('node="nodo-test"', text)

    def test_client_fails_over_when_one_node_is_down(self):
        dead = "http://127.0.0.1:9"            # nadie escucha aquí
        client = FailoverClient([dead, self.urls[0]], timeout=0.5, max_attempts=3)
        rng = np.random.default_rng(8)
        results = [client.predict(payload(rng, "desgaste")) for _ in range(6)]
        self.assertTrue(all(r.ok for r in results))
        self.assertTrue(any(not r.first_try_ok for r in results))   # alguna usó el reintento


if __name__ == "__main__":
    unittest.main()
