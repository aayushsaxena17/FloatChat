# Forecast evaluation (2026-10-16)

Commit `07eef952660ed86c04442b5c8174726bc8f1659c`; grid `full` (8 series); folds 12; horizons [1, 2, 3]; forecast horizon 3; seed 20261016; statsmodels 0.14.6, scipy 1.18.1, numpy 2.5.3. Protocol: rolling-origin, expanding window, refit per fold (PRD §30.4, ADR-0084). MASE is scaled by the in-sample MAE of the seasonal naive on each fold's training window; a candidate is selected only when its mean MASE beats the baseline by at least 5% and its residuals pass Ljung-Box at lag 12.

## Series

| Series | Snapshot | Dataset version | Months | Status | Selected | Baseline MASE (h1/h2/h3) | Selected MASE (h1/h2/h3) | Coverage 80/95 (selected) | Reason |
|---|---|---|---|---|---|---|---|---|---|
| Andaman Sea salinity | `bb3efeeb` | `8562e75d/27` | 0 | refused | - | - | - | - | history_too_short: No month has enough profiles for a value. |
| Andaman Sea temperature | `eb0d6090` | `8562e75d/27` | 0 | refused | - | - | - | - | history_too_short: No month has enough profiles for a value. |
| Arabian Sea salinity | `0647a52f` | `8562e75d/27` | 120 | published | SARIMA(1,0,0)(0,0,0)[12] + c | 2.253/2.254/2.340 | 0.941/1.556/2.258 | 0.39/0.58 |  |
| Arabian Sea temperature | `d46c404c` | `8562e75d/27` | 120 | published | SARIMA(0,1,0)(0,1,1)[12] | 1.936/1.674/1.417 | 0.454/0.431/0.437 | 0.86/0.97 |  |
| Bay of Bengal salinity | `b4b3ff9b` | `8562e75d/27` | 72 | published | SARIMA(1,0,0)(0,0,0)[12] + c | 1.456/1.418/1.280 | 0.491/0.616/0.662 | 0.86/1.00 |  |
| Bay of Bengal temperature | `8905fea6` | `8562e75d/27` | 72 | experimental | - | 0.836/0.893/0.918 | - | - | SARIMA(0,0,2)(1,1,0)[12]: mean MASE 1.019 does not beat the baseline 0.883 by 5%; SARIMA(0,0,2)(0,1,1)[12]: mean MASE 0.936 does not beat the baseline 0.883 by 5% |
| Laccadive Sea salinity | `62abe562` | `8562e75d/27` | 106 | refused | - | - | - | - | missingness_exceeds_policy: 14 of 120 months (12%) are missing and the longest gap is 4 months; the policy allows 20% and gaps of 2. |
| Laccadive Sea temperature | `70068660` | `8562e75d/27` | 120 | experimental | - | 1.347/1.493/1.470 | - | - | SARIMA(1,0,0)(0,1,1)[12]: residual diagnostics failed; SARIMA(2,0,0)(0,1,1)[12]: residual diagnostics failed |

Baseline beaten (model published): 3; baseline wins (experimental): 2; refused: 3.

## Candidates per series (mean MASE over the horizons)

| Series | Candidate | Mean MASE | MAE h1 | RMSE h1 | Coverage 80 h1 | Coverage 95 h1 | Misses |
|---|---|---|---|---|---|---|---|
| Arabian Sea salinity | seasonal naive (12) | 2.282 | 0.295 | 0.337 | 0.42 | 0.50 | 0 |
| Arabian Sea salinity | SARIMA(1,0,0)(0,0,1)[12] + c | 1.576 | 0.126 | 0.158 | 0.50 | 0.75 | 0 |
| Arabian Sea salinity | SARIMA(1,0,0)(0,0,0)[12] + c | 1.585 | 0.123 | 0.153 | 0.42 | 0.75 | 0 |
| Arabian Sea salinity | SARIMA(1,0,1)(0,0,1)[12] + c | 1.548 | 0.134 | 0.164 | 0.42 | 0.67 | 0 |
| Arabian Sea temperature | seasonal naive (12) | 1.676 | 1.001 | 1.198 | 0.42 | 0.67 | 0 |
| Arabian Sea temperature | SARIMA(2,0,0)(1,0,0)[12] + c | 0.635 | 0.300 | 0.385 | 0.70 | 0.90 | 6 |
| Arabian Sea temperature | SARIMA(1,0,0)(0,1,1)[12] | 0.418 | 0.231 | 0.284 | 0.75 | 0.92 | 0 |
| Arabian Sea temperature | SARIMA(0,1,0)(0,1,1)[12] | 0.441 | 0.239 | 0.295 | 0.67 | 0.92 | 0 |
| Bay of Bengal salinity | seasonal naive (12) | 1.384 | 0.308 | 0.338 | 0.50 | 1.00 | 0 |
| Bay of Bengal salinity | SARIMA(1,0,0)(0,0,0)[12] + c | 0.589 | 0.104 | 0.120 | 0.83 | 1.00 | 0 |
| Bay of Bengal salinity | SARIMA(2,0,0)(0,0,0)[12] + c | 0.597 | 0.106 | 0.121 | 0.83 | 1.00 | 0 |
| Bay of Bengal salinity | SARIMA(1,0,1)(0,0,0)[12] + c | 0.593 | 0.106 | 0.121 | 0.83 | 1.00 | 0 |
| Bay of Bengal temperature | seasonal naive (12) | 0.883 | 0.360 | 0.529 | 0.83 | 0.92 | 0 |
| Bay of Bengal temperature | SARIMA(0,0,2)(1,1,0)[12] | 1.019 | 0.395 | 0.490 | 0.58 | 0.92 | 0 |
| Bay of Bengal temperature | SARIMA(0,0,2)(0,1,1)[12] | 0.936 | 0.368 | 0.442 | 0.75 | 0.92 | 0 |
| Bay of Bengal temperature | SARIMA(1,0,2)(1,1,0)[12] | 0.968 | 0.380 | 0.476 | 0.58 | 0.92 | 0 |
| Laccadive Sea temperature | seasonal naive (12) | 1.437 | 0.860 | 0.989 | 0.58 | 0.92 | 0 |
| Laccadive Sea temperature | SARIMA(1,0,0)(0,1,1)[12] | 1.201 | 0.548 | 0.760 | 0.75 | 0.83 | 0 |
| Laccadive Sea temperature | SARIMA(1,0,0)(1,1,1)[12] | 1.218 | 0.552 | 0.776 | 0.75 | 0.83 | 0 |
| Laccadive Sea temperature | SARIMA(2,0,0)(0,1,1)[12] | 1.187 | 0.546 | 0.756 | 0.75 | 0.83 | 0 |

## Diagnostics and warnings

- Andaman Sea salinity: refused (history_too_short).
- Andaman Sea temperature: refused (history_too_short).
- Arabian Sea salinity: published; Ljung-Box p 0.451; residual mean -0.0010; no warnings
- Arabian Sea temperature: published; Ljung-Box p 0.074; residual mean 0.1083; SARIMA(2,0,0)(1,0,0)[12] + c: the forecast diverged in 2 fold(s)
- Bay of Bengal salinity: published; Ljung-Box p 0.786; residual mean -0.0012; no warnings
- Bay of Bengal temperature: experimental; Ljung-Box p -; residual mean -; SARIMA(0,0,2)(1,1,0)[12]: mean MASE 1.019 does not beat the baseline 0.883 by 5%; SARIMA(0,0,2)(0,1,1)[12]: mean MASE 0.936 does not beat the baseline 0.883 by 5%; SARIMA(1,0,2)(1,1,0)[12]: mean MASE 0.968 does not beat the baseline 0.883 by 5%; No SARIMA candidate beat the seasonal-naive baseline by the configured margin and passed diagnostics; the baseline forecast is shown and is not authoritative.
- Laccadive Sea salinity: refused (missingness_exceeds_policy).
- Laccadive Sea temperature: experimental; Ljung-Box p -; residual mean -; SARIMA(1,0,0)(0,1,1)[12]: residual diagnostics failed; SARIMA(2,0,0)(0,1,1)[12]: residual diagnostics failed; SARIMA(1,0,0)(1,1,1)[12]: residual diagnostics failed; 5 months were interpolated: 2022-07, 2022-10, 2022-12, 2023-01, 2024-02; No SARIMA candidate beat the seasonal-naive baseline by the configured margin and passed diagnostics; the baseline forecast is shown and is not authoritative.

Interpretation boundary (PRD §12.4): every run carries the text that it is a statistical extrapolation of a derived observational series, not a physics-based ocean forecast.
