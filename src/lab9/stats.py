"""Statistics students implement (M2 judge calibration, M4 paired bootstrap).

Rules: a judge is a classifier -- measure it like one. A higher mean is not
"better" until the paired CI of the difference excludes 0.
Reference values to self-check are in tests/test_lab9_stats.py.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

POS = "FAIL"   # the judge's job is to FIND failures, so FAIL is the positive class


def _pairs(human: Sequence[str], judge: Sequence[str]) -> list[tuple[str, str]]:
    if len(human) != len(judge):
        raise ValueError(f"human and judge lengths differ: {len(human)} != {len(judge)}")
    return [(h, j) for h, j in zip(human, judge)]


def confusion(human: Sequence[str], judge: Sequence[str]) -> dict[str, int]:
    """tp/fp/fn/tn with FAIL as positive."""
    counts = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for h, j in _pairs(human, judge):
        if j == POS:
            counts["tp" if h == POS else "fp"] += 1
        else:
            counts["fn" if h == POS else "tn"] += 1
    return counts


def precision_recall(human: Sequence[str], judge: Sequence[str]) -> tuple[float, float]:
    # precision = tp/(tp+fp), recall = tp/(tp+fn); 0.0 when the denominator is 0
    cm = confusion(human, judge)
    precision = cm["tp"] / (cm["tp"] + cm["fp"]) if cm["tp"] + cm["fp"] else 0.0
    recall = cm["tp"] / (cm["tp"] + cm["fn"]) if cm["tp"] + cm["fn"] else 0.0
    return precision, recall


def cohen_kappa(human: Sequence[str], judge: Sequence[str]) -> float:
    """kappa = (p_o - p_e) / (1 - p_e). Raise ValueError when undefined (p_e == 1):
    a constant judge has no signal and must FAIL calibration, not pass on a technicality."""
    pairs = _pairs(human, judge)
    n = len(pairs)
    if n == 0:
        raise ValueError("kappa undefined on an empty sample")
    p_o = sum(h == j for h, j in pairs) / n
    p_human_fail = sum(h == POS for h, _ in pairs) / n
    p_judge_fail = sum(j == POS for _, j in pairs) / n
    p_e = p_human_fail * p_judge_fail + (1 - p_human_fail) * (1 - p_judge_fail)
    if math.isclose(p_e, 1.0):
        raise ValueError("kappa undefined: p_e == 1 (the judge or the labels are constant)")
    return (p_o - p_e) / (1 - p_e)


def rogan_gladen(observed_rate: float, sensitivity: float, specificity: float) -> float:
    """Correct an observed failure rate for judge error; clip to [0, 1]."""
    denom = sensitivity + specificity - 1
    if denom == 0:
        # A judge at chance carries no information; the honest answer is "unknown", and a
        # rate we cannot correct must not be reported as if it were corrected.
        raise ValueError("Rogan-Gladen undefined: sensitivity + specificity == 1")
    return min(1.0, max(0.0, (observed_rate + specificity - 1) / denom))


def paired_bootstrap(a: Sequence[float], b: Sequence[float], *, n_resamples: int = 1000,
                     rng: int = 2027, confidence: float = 0.95) -> tuple[float, float, float]:
    """a[i], b[i] = per-item mean over seeds, SAME items, SAME order.
    Return (mean(a)-mean(b), lo, hi) with scipy.stats.bootstrap(paired=True, method="percentile",
    rng=numpy.random.default_rng(rng)). If a == b everywhere return (0.0, 0.0, 0.0)."""
    a_arr = np.asarray(a, dtype=float)
    b_arr = np.asarray(b, dtype=float)
    if a_arr.shape != b_arr.shape:
        raise ValueError(f"paired bootstrap needs the same items: {a_arr.shape} != {b_arr.shape}")
    diff = float(a_arr.mean() - b_arr.mean()) if len(a_arr) else 0.0
    if np.array_equal(a_arr, b_arr):
        return 0.0, 0.0, 0.0
    if len(a_arr) < 2:
        return diff, diff, diff
    from scipy.stats import bootstrap

    res = bootstrap((a_arr, b_arr), lambda x, y: float(np.mean(x) - np.mean(y)),
                    paired=True, vectorized=False, n_resamples=n_resamples,
                    confidence_level=confidence, method="percentile",
                    rng=np.random.default_rng(rng))
    lo, hi = (float(v) for v in res.confidence_interval)
    return diff, lo, hi


def _check_pass_k(n: int, c: int, k: int) -> None:
    if not isinstance(n, int) or not isinstance(c, int) or not isinstance(k, int):
        raise ValueError(f"pass@k/pass^k need integers, got n={n!r} c={c!r} k={k!r}")
    if n <= 0:
        raise ValueError(f"n must be >= 1, got {n}")
    if not 0 <= c <= n:
        raise ValueError(f"c must satisfy 0 <= c <= n, got c={c} n={n}")
    if not 1 <= k <= n:
        raise ValueError(f"k must satisfy 1 <= k <= n, got k={k} n={n}")


def pass_at_k(n: int, c: int, k: int) -> float:
    """Probability that AT LEAST ONE of k trials drawn from n (c of them passing) passes.
    Unbiased estimator (Chen et al. 2021): 1 - C(n-c, k) / C(n, k). Raise ValueError if k > n."""
    _check_pass_k(n, c, k)
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """pass^k (tau-bench, Yao et al. 2024): probability that ALL k trials drawn from n pass.
    Unbiased estimator: C(c, k) / C(n, k). Raise ValueError if k > n.
    pass^k <= pass@1 <= pass@k; a reliable agent keeps pass^k close to pass@1."""
    _check_pass_k(n, c, k)
    return math.comb(c, k) / math.comb(n, k)
