"""Baseline, SARIMA search, rolling backtests, selection and refusals on synthetic series."""

import math

import numpy as np
import pytest
from floatchat_core.forecast import models
from floatchat_core.forecast.model import ForecastLimits
from floatchat_core.forecast.runner import run_forecast
from floatchat_core.forecast.series import (
    Refusal,
    SeriesSnapshot,
    apply_missing_policy,
    check_eligibility,
)

LIMITS = ForecastLimits(grid="small", folds=6, candidates=2)


def months(n: int, start_year: int = 2015) -> list[str]:
    return [f"{start_year + i // 12}-{i % 12 + 1:02d}" for i in range(n)]


def seasonal_series(n: int = 96, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    return 28 + 0.01 * t + 2.0 * np.sin(2 * np.pi * t / 12) + rng.normal(0, 0.15, n)


def snapshot(values, counts=None, start_year: int = 2015) -> SeriesSnapshot:
    values = list(values)
    return SeriesSnapshot(
        id="s",
        definition={"variable": "temperature", "region": "Arabian Sea"},
        dataset_version={"id": "env"},
        months=months(len(values), start_year),
        values=values,
        counts=list(counts) if counts is not None else [10] * len(values),
        partitions=[],
        versions={},
        built_at="2026-10-16T00:00:00Z",
        application_commit="test",
    )


def test_seasonal_naive_repeats_last_year_with_empirical_intervals() -> None:
    train = np.array([float(i % 12) for i in range(36)])
    prediction = models.seasonal_naive(train, 3, 12)
    assert prediction.mean.tolist() == [0.0, 1.0, 2.0]
    assert np.all(prediction.lower95 <= prediction.lower80) and np.all(
        prediction.upper80 <= prediction.upper95
    )
    assert math.isnan(models.mase_scale(train[:12], 12))
    assert models.mase_scale(train, 12) == 0.0 or math.isnan(models.mase_scale(train, 12))


def test_sarima_beats_the_baseline_on_a_seasonal_series_with_trend() -> None:
    series = seasonal_series()
    first_train = series[: series.size - LIMITS.folds - max(LIMITS.horizons) + 1]
    ranked, ledger = models.rank_candidates(first_train, LIMITS)
    assert 1 <= len(ranked) <= LIMITS.candidates and len(ledger) == 6
    backtest = models.rolling_backtest(series, [models.BASELINE, *ranked], LIMITS)
    baseline = backtest[models.BASELINE.label]
    assert baseline["folds"] == LIMITS.folds and set(baseline["horizons"]) == {"1", "2", "3"}
    best = min(backtest[c.label]["mean_mase"] for c in ranked)
    assert best < baseline["mean_mase"]
    selection = models.select(series, backtest, [models.BASELINE, *ranked], LIMITS)
    assert selection.selected is not None and selection.status == "published"
    assert selection.diagnostics["passed"] is True
    chosen, prediction, params = models.final_forecast(series, selection, 3, LIMITS)
    assert chosen.family == "sarima" and len(prediction.mean) == 3 and params
    assert np.all(prediction.lower95 < prediction.mean) and np.all(
        prediction.mean < prediction.upper95
    )


def test_a_candidate_short_of_the_margin_leaves_the_run_experimental() -> None:
    # On white noise a mean model beats the seasonal naive by a lot; with the improvement
    # margin raised far above that, no candidate qualifies and the baseline is shown as such.
    rng = np.random.default_rng(7)
    series = 35 + rng.normal(0, 0.1, 84)
    outcome = run_forecast(
        snapshot(series), 3, ForecastLimits(grid="small", folds=6, candidates=2, improvement=0.9)
    )
    assert outcome["status"] == "experimental"
    assert outcome["forecast"]["model"]["family"] == "seasonal_naive"
    assert any("baseline" in warning for warning in outcome["warnings"])
    assert models.BASELINE.label in outcome["backtest"]["results"]
    assert outcome["backtest"]["candidates_carried"]
    assert outcome["versions"]["statsmodels"] and outcome["versions"]["seed"] == LIMITS.seed
    assert all("does not beat" in reason for reason in outcome["selection"]["reasons"])


def test_published_run_document_carries_history_forecast_backtest_and_fill_flags() -> None:
    series = seasonal_series().tolist()
    values = list(series)
    values[40] = None  # one interior month below the profile threshold
    counts = [10] * len(values)
    counts[40] = 2
    outcome = run_forecast(snapshot(values, counts), 2, LIMITS)
    assert outcome["status"] in ("published", "experimental")
    history = outcome["history"]
    assert history["filled"][40] is True and sum(history["filled"]) == 1
    assert history["policy"]["filled_months"] == [months(96)[40]]
    assert outcome["forecast"]["months"] == ["2023-01", "2023-02"]
    assert len(outcome["forecast"]["mean"]) == 2 and len(outcome["forecast"]["lower80"]) == 2
    assert outcome["backtest"]["folds"] == LIMITS.folds
    assert outcome["selection"]["improvement_required"] == LIMITS.improvement


@pytest.mark.parametrize(
    ("values", "counts", "horizon", "code"),
    [
        ([28.0] * 20, None, 3, "history_too_short"),
        ([28.0 + (i % 12) for i in range(48)], None, 13, "horizon_disproportionate"),
        ([28.0] * 48, None, 3, "series_constant"),
    ],
)
def test_refusal_rules(values, counts, horizon, code) -> None:
    outcome = run_forecast(snapshot(values, counts), horizon, LIMITS)
    assert outcome["status"] == "refused" and outcome["refusal_code"] == code
    assert "forecast" not in outcome and outcome["history"]["values"]


def test_missing_policy_trims_edges_interpolates_short_gaps_and_refuses_long_ones() -> None:
    limits = ForecastLimits(min_months=24)
    values: list[float | None] = [None, None, *[float(i) for i in range(30)], None]
    values[10] = None
    values[20] = values[21] = None
    regular = apply_missing_policy(months(len(values)), values, [10] * len(values), limits)
    assert regular.months[0] == months(len(values))[2] and len(regular.values) == 30
    assert regular.values[8] == pytest.approx(8.0) and regular.filled[8] is True
    assert regular.values[18] == pytest.approx(18.0) and regular.values[19] == pytest.approx(19.0)
    assert regular.policy["months_missing"] == 3 and regular.policy["longest_gap"] == 2
    assert regular.policy["trimmed_leading"] == 2 and regular.policy["trimmed_trailing"] == 1
    long_gap = list(values)
    long_gap[14:17] = [None, None, None]
    with pytest.raises(Refusal) as refused:
        apply_missing_policy(months(len(long_gap)), long_gap, [10] * len(long_gap), limits)
    assert refused.value.code == "missingness_exceeds_policy"
    check_eligibility(regular, 3, limits)
    with pytest.raises(Refusal, match="quarter"):
        check_eligibility(regular, 12, limits)


def test_the_full_grid_has_144_orders_and_the_small_grid_six() -> None:
    assert len(models.candidate_grid(ForecastLimits())) == 144
    assert len(models.candidate_grid(ForecastLimits(grid="small"))) == 6
    assert all(
        c.trend == "c"
        for c in models.candidate_grid(ForecastLimits())
        if c.order[1] == 0 and c.seasonal_order[1] == 0
    )
