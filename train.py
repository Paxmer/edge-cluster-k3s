#!/usr/bin/env python3
"""Genera el dataset simulado, compara modelos, entrena el elegido y guarda métricas.

Uso:  python train.py [--n-per-class 2000] [--seed 42] [--out artifacts]

Salidas en artifacts/: model.joblib, metrics.json, model_comparison.csv,
confusion_matrix.png y feature_importance.png (si el modelo lo permite).

OJO: los datos son sintéticos. Las métricas describen el desempeño sobre ESTOS
datos; para afirmar "datos reales" hay que repetir el entrenamiento con un
dataset público (por ejemplo CWRU o NASA IMS) y reportarlo por separado.
"""
import argparse
import csv
import json
import os
import platform
import time

import joblib
import matplotlib
import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import ConfusionMatrixDisplay, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

from edgekit.features import FEATURE_NAMES, extract_features
from edgekit.signals import CLASSES, make_window_for_class

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def build_dataset(n_per_class, seed):
    rng = np.random.default_rng(seed)
    X, y = [], []
    for label, name in enumerate(CLASSES):
        for _ in range(n_per_class):
            temp, vib = make_window_for_class(rng, name)
            X.append(extract_features(temp, vib))
            y.append(label)
    return np.array(X), np.array(y)


def candidate_models(seed):
    return {
        "Regresion logistica": make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000)),
        "Arbol de decision": DecisionTreeClassifier(max_depth=8, random_state=seed),
        "Random Forest": RandomForestClassifier(n_estimators=100, max_depth=12, random_state=seed, n_jobs=1),
        "Gradient Boosting": HistGradientBoostingClassifier(max_iter=150, random_state=seed),
    }


def single_prediction_latency_ms(model, x_row, repeats=300):
    row = x_row.reshape(1, -1)
    model.predict_proba(row)  # calentamiento
    times = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        model.predict_proba(row)
        times.append((time.perf_counter() - t0) * 1000)
    return float(np.median(times))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-per-class", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="artifacts")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    X, y = build_dataset(args.n_per_class, args.seed)
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.25, stratify=y, random_state=args.seed)
    print(f"Dataset: {len(X)} lecturas ({args.n_per_class} por clase), {X.shape[1]} características")

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=args.seed)
    rows, fitted = [], {}
    for name, model in candidate_models(args.seed).items():
        cv_f1 = cross_val_score(model, X_tr, y_tr, cv=cv, scoring="f1_macro")
        model.fit(X_tr, y_tr)
        pred = model.predict(X_te)
        tmp = os.path.join(args.out, "_tmp.joblib")
        joblib.dump(model, tmp, compress=3)
        size_kb = os.path.getsize(tmp) / 1024
        os.remove(tmp)
        rows.append({
            "modelo": name,
            "cv_f1_macro_media": round(float(cv_f1.mean()), 4),
            "cv_f1_macro_desv": round(float(cv_f1.std()), 4),
            "test_accuracy": round(float((pred == y_te).mean()), 4),
            "test_f1_macro": round(float(f1_score(y_te, pred, average="macro")), 4),
            "latencia_ms_por_lectura": round(single_prediction_latency_ms(model, X_te[0]), 3),
            "tamano_kb": round(size_kb, 1),
        })
        fitted[name] = model
        print(f"  {name:22s} CV F1={rows[-1]['cv_f1_macro_media']:.4f}  test acc={rows[-1]['test_accuracy']:.4f}"
              f"  {rows[-1]['latencia_ms_por_lectura']} ms  {rows[-1]['tamano_kb']} KB")

    best = max(rows, key=lambda r: (r["cv_f1_macro_media"], -r["tamano_kb"]))
    chosen_name = best["modelo"]
    chosen = fitted[chosen_name]
    pred = chosen.predict(X_te)
    cm = confusion_matrix(y_te, pred)
    report = classification_report(y_te, pred, target_names=CLASSES, output_dict=True)
    print(f"\nModelo elegido: {chosen_name}")
    print(classification_report(y_te, pred, target_names=CLASSES))

    joblib.dump({"model": chosen, "classes": CLASSES, "feature_names": FEATURE_NAMES,
                 "model_name": chosen_name, "sklearn_version": sklearn.__version__},
                os.path.join(args.out, "model.joblib"), compress=3)

    with open(os.path.join(args.out, "model_comparison.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    importances = None
    if hasattr(chosen, "feature_importances_"):
        importances = {n: round(float(v), 4) for n, v in zip(FEATURE_NAMES, chosen.feature_importances_)}
        order = np.argsort(chosen.feature_importances_)
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.barh([FEATURE_NAMES[i] for i in order], chosen.feature_importances_[order], color="#4c6fbf")
        ax.set_xlabel("Importancia")
        ax.set_title(f"Importancia de características ({chosen_name})")
        fig.tight_layout()
        fig.savefig(os.path.join(args.out, "feature_importance.png"), dpi=150)
        plt.close(fig)

    fig, ax = plt.subplots(figsize=(5, 4.5))
    ConfusionMatrixDisplay(cm, display_labels=CLASSES).plot(ax=ax, cmap="Blues", colorbar=False)
    ax.set_title(f"Matriz de confusión ({chosen_name}, datos sintéticos)")
    fig.tight_layout()
    fig.savefig(os.path.join(args.out, "confusion_matrix.png"), dpi=150)
    plt.close(fig)

    metrics = {
        "advertencia": "Datos SINTETICOS generados con edgekit.signals; no son mediciones reales.",
        "modelo_elegido": chosen_name,
        "criterio_de_eleccion": "mayor F1 macro en validacion cruzada (5 folds); desempate por menor tamano",
        "n_lecturas": int(len(X)), "n_por_clase": args.n_per_class, "seed": args.seed,
        "entrenamiento": int(len(X_tr)), "prueba": int(len(X_te)),
        "test_accuracy": float((pred == y_te).mean()),
        "reporte_por_clase": report,
        "matriz_confusion": {"filas_real_columnas_predicho": CLASSES, "valores": cm.tolist()},
        "importancia_caracteristicas": importances,
        "comparacion_modelos": rows,
        "entorno": {"python": platform.python_version(), "sklearn": sklearn.__version__,
                    "numpy": np.__version__, "maquina": platform.machine(),
                    "nota_latencia": "medida en la maquina donde se entreno; repetir en los mini PC"},
    }
    with open(os.path.join(args.out, "metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    print(f"Artefactos guardados en {args.out}/")


if __name__ == "__main__":
    main()
