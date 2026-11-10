"""Tracking diagnostics on the original time grid; no alignment of scored data."""
import numpy as np


def tracking_metrics(frame, timestep_minutes):
    target = frame["target_delta_kw"].to_numpy(dtype=float)
    actual = frame["Actual Delta (kW)"].to_numpy(dtype=float)
    if not len(target) or not np.isfinite([target, actual]).all():
        raise ValueError("Tracking data must be finite and nonempty")
    def correlation(x, y):
        if len(x) < 3 or np.std(x) < 1e-12 or np.std(y) < 1e-12:
            return None
        return float(np.corrcoef(x, y)[0, 1])
    zero = correlation(target, actual)
    best, lag = zero, 0
    # Positive lag means actual response trails the target. A sine can have
    # ambiguous periodic peaks; search only up to ten minutes and half the run.
    maximum = min(int(10 / timestep_minutes), max(0, (len(target) - 3) // 2))
    for k in range(1, maximum + 1):
        value = correlation(target[:-k], actual[k:])
        if value is not None and (best is None or value > best):
            best, lag = value, k
    energy = float(np.dot(target, target))
    target_rms = float(np.sqrt(energy / len(target)))
    rmse = float(np.sqrt(np.mean((target - actual) ** 2)))
    return {"normalized_tracking_rmse": rmse / target_rms if target_rms else None,
            "tracking_rmse_kw": float(np.sqrt(np.mean((target - actual) ** 2))),
            "tracking_mae_kw": float(np.mean(np.abs(target - actual))),
            "zero_lag_correlation": zero, "best_correlation": best,
            "best_lag_minutes": lag * timestep_minutes if best is not None else None,
            "actual_target_rms_ratio": float(np.sqrt(np.dot(actual, actual) / energy)) if energy else None,
            "through_origin_gain": float(np.dot(target, actual) / energy) if energy else None,
            "lag_search_max_minutes": maximum * timestep_minutes}
