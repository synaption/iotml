"""
Basic ML training example for iotml.

Trains a logistic-regression classifier on a synthetic tabular dataset
using scikit-learn so it runs quickly in CI with no GPU required.
Outputs:
  - model.joblib  — saved model
  - metrics.json  — accuracy, precision, recall, F1 on the test split
"""

import json
import os
import sys

import joblib
import numpy as np
from sklearn.datasets import make_classification
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

# ---------------------------------------------------------------------------
# Hyper-parameters (can be overridden via environment variables)
# ---------------------------------------------------------------------------
N_SAMPLES = int(os.getenv("N_SAMPLES", "2000"))
N_FEATURES = int(os.getenv("N_FEATURES", "20"))
N_CLASSES = int(os.getenv("N_CLASSES", "2"))
RANDOM_STATE = int(os.getenv("RANDOM_STATE", "42"))
TEST_SIZE = float(os.getenv("TEST_SIZE", "0.2"))
OUTPUT_DIR = os.getenv("OUTPUT_DIR", ".")


def generate_dataset(
    n_samples: int,
    n_features: int,
    n_classes: int,
    random_state: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Return a synthetic classification dataset."""
    X, y = make_classification(
        n_samples=n_samples,
        n_features=n_features,
        n_informative=max(n_features // 2, 2),
        n_redundant=max(n_features // 4, 1),
        n_classes=n_classes,
        random_state=random_state,
    )
    return X, y


def build_model() -> Pipeline:
    """Return a simple, fast baseline pipeline suitable for edge deployment."""
    return Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "clf",
                LogisticRegression(
                    max_iter=500,
                    solver="lbfgs",
                ),
            ),
        ]
    )


def evaluate(model: Pipeline, X_test: np.ndarray, y_test: np.ndarray, n_train: int) -> dict:
    """Return a dict of evaluation metrics."""
    avg = "binary" if len(np.unique(y_test)) == 2 else "macro"
    y_pred = model.predict(X_test)
    return {
        "accuracy": round(float(accuracy_score(y_test, y_pred)), 4),
        "precision": round(float(precision_score(y_test, y_pred, average=avg, zero_division=0)), 4),
        "recall": round(float(recall_score(y_test, y_pred, average=avg, zero_division=0)), 4),
        "f1": round(float(f1_score(y_test, y_pred, average=avg, zero_division=0)), 4),
        "n_train": n_train,
        "n_test": int(len(y_test)),
    }


def main() -> None:
    print(f"Generating synthetic dataset: {N_SAMPLES} samples, {N_FEATURES} features, {N_CLASSES} classes")
    X, y = generate_dataset(N_SAMPLES, N_FEATURES, N_CLASSES, RANDOM_STATE)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y
    )
    print(f"Train split: {len(X_train)} samples | Test split: {len(X_test)} samples")

    model = build_model()
    print("Training model…")
    model.fit(X_train, y_train)

    metrics = evaluate(model, X_test, y_test, n_train=len(X_train))
    print("\nEvaluation metrics:")
    for name, value in metrics.items():
        print(f"  {name}: {value}")

    # Persist outputs
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    model_path = os.path.join(OUTPUT_DIR, "model.joblib")
    metrics_path = os.path.join(OUTPUT_DIR, "metrics.json")

    joblib.dump(model, model_path)
    print(f"\nModel saved to: {model_path}")

    with open(metrics_path, "w", encoding="utf-8") as fp:
        json.dump(metrics, fp, indent=2)
    print(f"Metrics saved to: {metrics_path}")

    # Fail loudly in CI if accuracy is unacceptably low
    min_accuracy = float(os.getenv("MIN_ACCURACY", "0.70"))
    if metrics["accuracy"] < min_accuracy:
        print(f"\nERROR: accuracy {metrics['accuracy']} is below threshold {min_accuracy}", file=sys.stderr)
        sys.exit(1)

    print("\nTraining complete.")


if __name__ == "__main__":
    main()
