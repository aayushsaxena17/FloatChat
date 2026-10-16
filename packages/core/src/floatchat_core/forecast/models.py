"""Seasonal-naive baseline, bounded SARIMA search, rolling-origin backtests, selection (ADR-0084).

Everything here works on a regular monthly series as a float array with no missing values (the
missing policy of ``series.py`` runs first). Fits are deterministic for given data; the seed is
set for any randomised step and recorded with the run.
"""

import math
import warnings
from dataclasses import dataclass, field
from itertools import product
from typing import Any

import numpy as np

from .model import ForecastLimits

Order = tuple[int, int, int]
SeasonalOrder = tuple[int, int, int, int]
QUANTILES = {"80": 0.8, "95": 0.95}


@dataclass(frozen=True)
class Candidate:
    family: str  # seasonal_naive | sarima
    order: Order = (0, 0, 0)
    seasonal_order: SeasonalOrder = (0, 0, 0, 0)
    trend: str = "n"

    @property
    def label(self) -> str:
        if self.family == "seasonal_naive":
            return "seasonal naive (12)"
        p, d, q = self.order
        P, D, Q, s = self.seasonal_order
        return f"SARIMA({p},{d},{q})({P},{D},{Q})[{s}]" + (" + c" if self.trend == "c" else "")

    @property
    def parameters(self) -> int:
        p, _d, q = self.order
        P, _D, Q, _s = self.seasonal_order
        return p + q + P + Q + (1 if self.trend == "c" else 0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "label": self.label,
            "order": list(self.order),
            "seasonal_order": list(self.seasonal_order),
            "trend": self.trend,
            "parameters": self.parameters,
        }


@dataclass(frozen=True)
class Prediction:
    mean: np.ndarray
    lower80: np.ndarray
    upper80: np.ndarray
    lower95: np.ndarray
    upper95: np.ndarray


@dataclass
class HorizonMetrics:
    errors: list[float] = field(default_factory=list)
    scaled: list[float] = field(default_factory=list)
    inside80: list[bool] = field(default_factory=list)
    inside95: list[bool] = field(default_factory=list)
    misses: int = 0

    def summary(self) -> dict[str, Any]:
        if not self.errors:
            return {"n": 0, "misses": self.misses}
        errors = np.array(self.errors)
        return {
            "n": int(errors.size),
            "misses": self.misses,
            "mae": float(np.mean(np.abs(errors))),
            "rmse": float(math.sqrt(np.mean(errors**2))),
            "mase": float(np.mean(self.scaled)) if self.scaled else None,
            "coverage80": float(np.mean(self.inside80)),
            "coverage95": float(np.mean(self.inside95)),
        }


BASELINE = Candidate("seasonal_naive")


SMALL_GRID: tuple[tuple[Order, tuple[int, int, int]], ...] = (
    ((0, 1, 1), (0, 1, 1)),
    ((1, 0, 0), (1, 0, 0)),
    ((0, 1, 1), (0, 0, 0)),
    ((1, 1, 0), (0, 1, 0)),
    ((2, 0, 0), (0, 1, 1)),
    ((0, 0, 1), (1, 0, 0)),
)


def candidate_grid(limits: ForecastLimits) -> list[Candidate]:
    """The bounded SARIMA grid of ADR-0084 (144 orders), seasonal period 12."""
    if limits.grid == "small":
        return [
            Candidate(
                "sarima",
                order,
                (*seasonal, limits.season),
                "c" if order[1] == 0 and seasonal[1] == 0 else "n",
            )
            for order, seasonal in SMALL_GRID
        ]
    grid = []
    for p, d, q, P, D, Q in product((0, 1, 2), (0, 1), (0, 1, 2), (0, 1), (0, 1), (0, 1)):
        trend = "c" if d == 0 and D == 0 else "n"
        grid.append(Candidate("sarima", (p, d, q), (P, D, Q, limits.season), trend))
    return grid[: limits.max_orders]


def mase_scale(train: np.ndarray, season: int) -> float:
    """In-sample mean absolute error of the seasonal naive on the training window."""
    if train.size <= season:
        return float("nan")
    scale = float(np.mean(np.abs(train[season:] - train[:-season])))
    return scale if scale > 0 else float("nan")


def seasonal_naive(train: np.ndarray, horizon: int, season: int) -> Prediction:
    """y[T+h] = y[T+h-season·k]; intervals from the empirical in-sample errors."""
    n = train.size
    mean = np.array([train[n - season + ((h - 1) % season)] for h in range(1, horizon + 1)])
    errors = train[season:] - train[:-season] if n > season else np.array([0.0])
    spread = np.abs(errors - np.mean(errors)) if errors.size else np.array([0.0])
    q80 = float(np.quantile(spread, QUANTILES["80"])) if spread.size else 0.0
    q95 = float(np.quantile(spread, QUANTILES["95"])) if spread.size else 0.0
    return Prediction(mean, mean - q80, mean + q80, mean - q95, mean + q95)


def _fit(candidate: Candidate, train: np.ndarray, limits: ForecastLimits) -> Any | None:
    from statsmodels.tsa.statespace.sarimax import SARIMAX

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = SARIMAX(
                train,
                order=candidate.order,
                seasonal_order=candidate.seasonal_order,
                trend=candidate.trend,
                enforce_stationarity=True,
                enforce_invertibility=True,
            )
            result = model.fit(disp=0, method="lbfgs", maxiter=limits.fit_maxiter)
    except Exception:
        return None
    if not np.isfinite(result.llf) or not np.all(np.isfinite(result.params)):
        return None
    return result


def _predict(result: Any, horizon: int) -> Prediction | None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            forecast = result.get_forecast(steps=horizon)
            mean = np.asarray(forecast.predicted_mean, dtype=float)
            ci80 = np.asarray(forecast.conf_int(alpha=0.2), dtype=float)
            ci95 = np.asarray(forecast.conf_int(alpha=0.05), dtype=float)
    except Exception:
        return None
    if not np.all(np.isfinite(mean)):
        return None
    return Prediction(mean, ci80[:, 0], ci80[:, 1], ci95[:, 0], ci95[:, 1])


def aicc(result: Any, n: int) -> float:
    k = int(result.params.size)
    aic = float(result.aic)
    denominator = n - k - 1
    return aic + (2 * k * (k + 1) / denominator if denominator > 0 else float("inf"))


def rank_candidates(
    train: np.ndarray, limits: ForecastLimits
) -> tuple[list[Candidate], list[dict[str, Any]]]:
    """Fit every order of the grid once on the first training window; the best by AICc go on."""
    scored: list[tuple[float, Candidate]] = []
    ledger: list[dict[str, Any]] = []
    for candidate in candidate_grid(limits):
        result = _fit(candidate, train, limits)
        if result is None:
            ledger.append({"candidate": candidate.label, "aicc": None, "fit": "failed"})
            continue
        score = aicc(result, int(train.size))
        ledger.append({"candidate": candidate.label, "aicc": score, "fit": "ok"})
        if math.isfinite(score):
            scored.append((score, candidate))
    scored.sort(key=lambda item: (item[0], item[1].parameters))
    return [candidate for _score, candidate in scored[: limits.candidates]], ledger


def predict_candidate(
    candidate: Candidate, train: np.ndarray, horizon: int, limits: ForecastLimits
) -> Prediction | None:
    if candidate.family == "seasonal_naive":
        return seasonal_naive(train, horizon, limits.season)
    result = _fit(candidate, train, limits)
    return None if result is None else _predict(result, horizon)


def rolling_backtest(
    series: np.ndarray, candidates: list[Candidate], limits: ForecastLimits
) -> dict[str, dict[str, Any]]:
    """Rolling-origin, expanding-window backtest; metrics per candidate per horizon."""
    horizon = max(limits.horizons)
    n = series.size
    first_origin = n - limits.folds - horizon + 1
    minimum = max(2 * limits.season + 1, 24)
    if first_origin < minimum:
        raise ValueError("history too short for the backtest")
    metrics: dict[str, dict[int, HorizonMetrics]] = {
        candidate.label: {h: HorizonMetrics() for h in limits.horizons} for candidate in candidates
    }
    diverged: dict[str, int] = {candidate.label: 0 for candidate in candidates}
    # A fit whose point forecast leaves the data's scale by three orders of magnitude has
    # diverged numerically (seen on a non-stationary order over the Arabian Sea series); it
    # is a miss for the fold and the candidate is reported, never selected.
    bound = 1000.0 * (float(np.max(np.abs(series))) + 1.0)
    for origin in range(first_origin, first_origin + limits.folds):
        train, future = series[:origin], series[origin : origin + horizon]
        scale = mase_scale(train, limits.season)
        for candidate in candidates:
            prediction = predict_candidate(candidate, train, horizon, limits)
            if prediction is not None and (
                not np.all(np.isfinite(prediction.mean)) or np.max(np.abs(prediction.mean)) > bound
            ):
                diverged[candidate.label] += 1
                prediction = None
            for h in limits.horizons:
                bucket = metrics[candidate.label][h]
                if prediction is None or h > future.size:
                    bucket.misses += 1
                    continue
                actual, mean = float(future[h - 1]), float(prediction.mean[h - 1])
                error = actual - mean
                bucket.errors.append(error)
                if math.isfinite(scale):
                    bucket.scaled.append(abs(error) / scale)
                bucket.inside80.append(
                    bool(prediction.lower80[h - 1] <= actual <= prediction.upper80[h - 1])
                )
                bucket.inside95.append(
                    bool(prediction.lower95[h - 1] <= actual <= prediction.upper95[h - 1])
                )
    report: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        per_horizon = {str(h): metrics[candidate.label][h].summary() for h in limits.horizons}
        values = [v["mase"] for v in per_horizon.values() if v.get("mase") is not None]
        report[candidate.label] = {
            "candidate": candidate.as_dict(),
            "horizons": per_horizon,
            "mean_mase": float(np.mean(values)) if values else None,
            "folds": limits.folds,
            "diverged_folds": diverged[candidate.label],
        }
    return report


def diagnose(residuals: np.ndarray, season: int) -> dict[str, Any]:
    """Ljung-Box at the seasonal lag and the residual mean, with the pass rule of ADR-0084."""
    from statsmodels.stats.diagnostic import acorr_ljungbox

    finite = residuals[np.isfinite(residuals)]
    if finite.size < season + 2:
        return {"ljung_box_p": None, "residual_mean": None, "passed": False}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        table = acorr_ljungbox(finite, lags=[season], return_df=True)
    p_value = float(table["lb_pvalue"].iloc[0])
    mean, std = float(np.mean(finite)), float(np.std(finite))
    centred = std == 0 or abs(mean) <= 0.1 * std
    return {
        "ljung_box_lag": season,
        "ljung_box_p": p_value,
        "residual_mean": mean,
        "residual_std": std,
        "passed": bool(p_value > 0.05 and centred and math.isfinite(p_value)),
    }


@dataclass(frozen=True)
class Selection:
    selected: Candidate | None
    status: str  # published | experimental
    reasons: list[str]
    diagnostics: dict[str, Any]
    fitted: Any | None = None


def select(
    series: np.ndarray,
    backtest: dict[str, dict[str, Any]],
    candidates: list[Candidate],
    limits: ForecastLimits,
) -> Selection:
    """The simplest candidate that materially beats the baseline and passes diagnostics."""
    baseline = backtest[BASELINE.label]["mean_mase"]
    reasons: list[str] = []
    if baseline is None:
        return Selection(None, "experimental", ["the baseline could not be scored"], {})
    eligible = []
    for candidate in candidates:
        if candidate.family == "seasonal_naive":
            continue
        mase = backtest[candidate.label]["mean_mase"]
        if mase is None:
            reasons.append(f"{candidate.label}: no backtest score")
            continue
        if backtest[candidate.label].get("diverged_folds"):
            reasons.append(
                f"{candidate.label}: the forecast diverged in "
                f"{backtest[candidate.label]['diverged_folds']} fold(s)"
            )
            continue
        if mase > baseline * (1 - limits.improvement):
            reasons.append(
                f"{candidate.label}: mean MASE {mase:.3f} does not beat the baseline "
                f"{baseline:.3f} by {limits.improvement:.0%}"
            )
            continue
        eligible.append((candidate.parameters, mase, candidate))
    eligible.sort(key=lambda item: (item[0], item[1]))
    for _parameters, _mase, candidate in eligible:
        result = _fit(candidate, series, limits)
        if result is None:
            reasons.append(f"{candidate.label}: the full-history fit failed")
            continue
        diagnostics = diagnose(np.asarray(result.resid, dtype=float), limits.season)
        if not diagnostics["passed"]:
            reasons.append(f"{candidate.label}: residual diagnostics failed")
            continue
        return Selection(candidate, "published", reasons, diagnostics, result)
    return Selection(None, "experimental", reasons, {})


def final_forecast(
    series: np.ndarray, selection: Selection, horizon: int, limits: ForecastLimits
) -> tuple[Candidate, Prediction, dict[str, Any]]:
    """The forecast of the selected model, or the baseline's when none was selected."""
    if selection.selected is None or selection.fitted is None:
        return BASELINE, seasonal_naive(series, horizon, limits.season), {}
    prediction = _predict(selection.fitted, horizon)
    if prediction is None:
        return BASELINE, seasonal_naive(series, horizon, limits.season), {}
    params = {
        name: float(value)
        for name, value in zip(selection.fitted.param_names, selection.fitted.params, strict=False)
    }
    return selection.selected, prediction, params
