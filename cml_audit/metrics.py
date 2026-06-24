from __future__ import annotations

from collections.abc import Callable

import numpy as np
from sklearn.metrics import roc_auc_score, roc_curve


def auroc(labels: np.ndarray, scores: np.ndarray) -> float:
    labels = np.asarray(labels)
    scores = np.asarray(scores)
    if len(np.unique(labels)) < 2:
        raise ValueError("AUROC requires both positive and negative labels.")
    return float(roc_auc_score(labels, scores))


def tpr_at_fpr(labels: np.ndarray, scores: np.ndarray, max_fpr: float = 0.01) -> float:
    labels = np.asarray(labels)
    scores = np.asarray(scores)
    if len(np.unique(labels)) < 2:
        raise ValueError("TPR at FPR requires both positive and negative labels.")
    fpr, tpr, _ = roc_curve(labels, scores)
    valid = tpr[fpr <= max_fpr]
    return float(valid.max()) if len(valid) else 0.0


def bootstrap_ci(
    values: np.ndarray,
    statistic: Callable[[np.ndarray], float] = np.mean,
    *,
    confidence: float = 0.95,
    n_bootstrap: int = 10_000,
    seed: int = 13,
) -> tuple[float, float, float]:
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or len(values) == 0:
        raise ValueError("bootstrap_ci expects a non-empty one-dimensional array.")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1.")

    rng = np.random.default_rng(seed)
    draws = rng.choice(values, size=(n_bootstrap, len(values)), replace=True)
    estimates = np.apply_along_axis(statistic, 1, draws)
    alpha = 1 - confidence
    lower = float(np.quantile(estimates, alpha / 2))
    upper = float(np.quantile(estimates, 1 - alpha / 2))
    point = float(statistic(values))
    return point, lower, upper
