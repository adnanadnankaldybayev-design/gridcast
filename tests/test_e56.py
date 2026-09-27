"""E5+E6 tests: conformal coverage calibration, ensemble past-only spy,
Diebold-Mariano sanity, reports retention policy."""

import numpy as np
import pandas as pd
import pytest

from gridcast.eval.conformal import conformal_frame
from gridcast.eval.dm import _hac_var, dm_test
from gridcast.eval.ensemble_eval import ensemble_frame, member_mae_by_anchor, weight_table


def _frame(anchors=60, err_sigma=100.0, seed=0):
    """Synthetic backtest frame: one shared deterministic actual series across
    all calls (seed only drives the MODEL error), so frames share an
    evaluation universe exactly like real member frames."""
    actual_rng = np.random.RandomState(0)
    err_rng = np.random.RandomState(seed)
    rows = []
    for j in range(anchors):
        anchor = pd.Timestamp("2026-03-01 12:00", tz="UTC") + pd.Timedelta(days=j)
        base = 5000.0 + actual_rng.normal(0, 50)
        for k in range(96):
            ts = anchor + pd.Timedelta(minutes=30 * (k + 1))
            actual = base + k
            predicted = actual + err_rng.normal(0, err_sigma)
            rows.append(
                {
                    "anchor": anchor,
                    "timestamp": ts,
                    "horizon_hours": (k + 1) * 0.5,
                    "actual": actual,
                    "predicted": predicted,
                    "warmup": False,
                }
            )
    return pd.DataFrame(rows)


def test_conformal_picp_hits_nominal_with_known_noise():
    """i.i.d. Gaussian residuals sigma=100: rolling split-conformal must cover
    ~nominal (tolerance ±0.04 — worth a real assertion, not a tautology)."""
    frame = _frame(anchors=60, err_sigma=100.0)
    conf, cov = conformal_frame(frame, levels=(80, 90, 95), calib_anchors=14)
    assert not conf.empty
    picp = dict(zip(cov["level"], cov["picp"], strict=True))
    for lv, expected in ((80, 0.80), (90, 0.90), (95, 0.95)):
        assert abs(picp[lv] - expected) < 0.04, f"PICP@{lv} = {picp[lv]}"
    # width grows with level
    w = dict(zip(cov["level"], cov["mean_width"], strict=True))
    assert w[80] < w[90] < w[95]
    # |err| 90% quantile ≈ 1.645sigma -> full width ≈ 3.29sigma (measured 3.26sigma)
    assert 300 < w[90] < 360


def test_ensemble_weights_use_only_past_anchors():
    """Spy criterion: corrupting any FUTURE anchor's residuals must not change
    earlier anchors' weights."""
    frames = {}
    for name, seed in (("a", 1), ("b", 2), ("c", 3)):
        frames[name] = _frame(anchors=40, seed=seed, err_sigma=100 * seed)
    maes = {m: member_mae_by_anchor(f) for m, f in frames.items()}
    w_clean = weight_table(maes).set_index("anchor")
    # corrupt residuals of all anchors after some anchor k0
    anchors = sorted(set().union(*(s.index for s in maes.values())))
    k0 = anchors[20]
    maes_dirty = {}
    for m, s in maes.items():
        d = s.copy()
        d.loc[d.index > k0] = 1e9  # catastrophic future error
        maes_dirty[m] = d
    w_dirty = weight_table(maes_dirty).set_index("anchor")
    earlier = w_clean.index <= k0
    pd.testing.assert_frame_equal(w_clean[earlier], w_dirty[earlier])
    # and later weights do absorb the shock (sanity that the data flows)
    assert not w_clean[~earlier].equals(w_dirty[~earlier])


def test_ensemble_beats_average_of_members_when_one_is_much_worse():
    good = _frame(seed=1, err_sigma=50)
    bad = _frame(seed=2, err_sigma=400)
    ens = ensemble_frame({"good": good, "bad": bad})
    mae_ens = (ens["actual"] - ens["predicted"]).abs().mean()
    mae_good = (good["actual"] - good["predicted"]).abs().mean()
    mae_bad = (bad["actual"] - bad["predicted"]).abs().mean()
    equal_avg = (mae_good + mae_bad) / 2
    assert mae_ens < equal_avg  # inverse-MAE weighting beats equal weights
    assert mae_ens < mae_bad


def test_dm_test_equal_models_p_high_different_p_low():
    """Same residuals -> no significant difference (p >> 0.05).
    Model2 with half the noise -> strongly significant (p < 0.05)."""
    f1 = _frame(anchors=60, seed=7, err_sigma=200)
    f2_same = f1.copy()
    out_same = dm_test(f1, f2_same)
    assert out_same["p_value_two_sided"] > 0.2

    f3 = _frame(anchors=60, seed=8, err_sigma=50)  # clearly better
    out_diff = dm_test(f1, f3)
    assert out_diff["p_value_two_sided"] < 0.05


def test_hac_var_collapses_to_iid_for_white_noise():
    rng = np.random.RandomState(5)
    x = rng.normal(0.0, 1.0, 5000)
    v = _hac_var(x, lag=10)
    assert v == pytest.approx(np.var(x, ddof=0) / len(x), rel=0.25)


def test_reports_retention_gitignore():
    import subprocess

    from gridcast.config import REPO_ROOT

    def ignored(path: str) -> bool:
        return (
            subprocess.run(
                ["git", "check-ignore", "-q", path], cwd=REPO_ROOT, capture_output=True
            ).returncode
            == 0
        )

    assert ignored("reports/backtest_x_20260101.json")
    assert not ignored("reports/latest_benchmark.json")
    assert not ignored("reports/latest_benchmark.md")
    assert not ignored("reports/BENCHMARK.md")
