"""Create an evidence-based tuning report for the HPWH fleet controller.

C0 reads the fleet-state CSV written by HPWH_B2.py. It separates tracking
quality, response delay, capacity saturation, command churn, and per-action
response estimates so controller settings can be tuned one at a time.
"""

import argparse
import ast
import os
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
except ModuleNotFoundError:
    mdates = None
    plt = None


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CAPACITY_PERCENTILE = 10.0
DEFAULT_MAX_LAG_MINUTES = 10.0

CORE_COLUMNS = {
    "Time",
    "Target Delta (kW)",
    "Actual HPWH Delta (kW)",
}

NUMERIC_COLUMNS = [
    "Regulation Signal",
    "Regulation Capacity (kW)",
    "Committed Regulation Capacity (kW)",
    "Target Before Capacity Limit (kW)",
    "Capacity-Limited Target (kW)",
    "Target Delta (kW)",
    "Actual Delta (kW)",
    "Actual HPWH Delta (kW)",
    "Tracking Error (kW)",
    "Previous Actual Delta (kW)",
    "Feedback Error (kW)",
    "Requested Adjustment (kW)",
    "Applied Adjustment (kW)",
    "Available Up Capacity (kW)",
    "Available Down Capacity (kW)",
    "Available Capacity in Requested Direction (kW)",
    "Estimated Dispatched Capacity (kW)",
    "Retained Capacity (kW)",
    "Units in NORMAL",
    "Units in SHED",
    "Units in LOAD",
    "Units Added to LOAD",
    "Units Released from LOAD",
    "Units Added to SHED",
    "Units Released from SHED",
    "Baseline HPWH Fleet Power (kW)",
    "Controlled HPWH Fleet Power (kW)",
    "Average Tank Temperature (C)",
]

SETTING_NAMES = {
    "COMMITTED_REGULATION_CAPACITY_KW",
    "EXPECTED_ON_POWER_KW",
    "FEEDBACK_GAIN",
    "TRACKING_DEADBAND_KW",
    "MAX_RESPONSE_CHANGE_KW_PER_INTERVAL",
    "MIN_HOLD_MINUTES",
    "CONTROL_INTERVAL_MINUTES",
}


def find_vpp_log(run_id, explicit_path=None):
    """Locate the requested B2 fleet-state log."""
    if explicit_path:
        path = Path(explicit_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"VPP state log not found: {path}")
        return path

    candidates = [
        SCRIPT_DIR / f"{run_id}_VPP_Fleet_States.csv",
        SCRIPT_DIR.parent / f"{run_id}_VPP_Fleet_States.csv",
    ]
    for path in candidates:
        if path.is_file():
            return path
    searched = "\n  ".join(str(path) for path in candidates)
    raise FileNotFoundError(
        f"Could not find the VPP state log. Searched:\n  {searched}"
    )


def read_controller_settings(b2_path=None):
    """Read literal tuning constants from B2 without importing OCHRE."""
    path = Path(b2_path) if b2_path else SCRIPT_DIR / "HPWH_B2.py"
    if not path.is_file():
        return {}

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    settings = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in SETTING_NAMES:
            continue
        try:
            settings[target.id] = ast.literal_eval(node.value)
        except (ValueError, TypeError):
            continue
    return settings


def load_vpp_data(path):
    """Load, validate, and derive common tuning fields."""
    df = pd.read_csv(path)
    missing = CORE_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(
            "VPP log is missing required columns: "
            + ", ".join(sorted(missing))
        )

    df["Time"] = pd.to_datetime(df["Time"], errors="coerce")
    present_numeric = [column for column in NUMERIC_COLUMNS if column in df]
    df[present_numeric] = df[present_numeric].apply(
        pd.to_numeric,
        errors="coerce",
    )
    df = (
        df.dropna(subset=list(CORE_COLUMNS))
        .sort_values("Time")
        .drop_duplicates(subset="Time")
        .reset_index(drop=True)
    )
    if df.empty:
        raise ValueError(f"No usable fleet-state rows were found in: {path}")

    time_diffs = df["Time"].diff().dt.total_seconds().div(60).dropna()
    timestep_minutes = float(time_diffs.median()) if not time_diffs.empty else 1.0
    if not np.isfinite(timestep_minutes) or timestep_minutes <= 0:
        timestep_minutes = 1.0

    if "Committed Regulation Capacity (kW)" in df:
        capacity = df["Committed Regulation Capacity (kW)"]
    elif "Regulation Capacity (kW)" in df:
        capacity = df["Regulation Capacity (kW)"]
    else:
        capacity = pd.Series(np.nan, index=df.index)

    df["Committed Capacity Used by C0 (kW)"] = capacity
    df["Calculated Tracking Error (kW)"] = (
        df["Target Delta (kW)"] - df["Actual HPWH Delta (kW)"]
    )
    df["Absolute Tracking Error (kW)"] = df[
        "Calculated Tracking Error (kW)"
    ].abs()
    df["Normalized Tracking Error"] = (
        df["Absolute Tracking Error (kW)"] / capacity.replace(0, np.nan)
    )
    df["Target Ramp (kW/min)"] = (
        df["Target Delta (kW)"].diff() / timestep_minutes
    )
    df["Actual Ramp (kW/min)"] = (
        df["Actual HPWH Delta (kW)"].diff() / timestep_minutes
    )

    if {
        "Available Up Capacity (kW)",
        "Available Down Capacity (kW)",
    }.issubset(df.columns):
        df["Available Bidirectional Capacity (kW)"] = df[
            ["Available Up Capacity (kW)", "Available Down Capacity (kW)"]
        ].min(axis=1)

    return df, timestep_minutes


def safe_percentile(series, percentile):
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return np.nan
    return float(np.percentile(values, percentile))


def safe_mean(series):
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.mean()) if not values.empty else np.nan


def safe_corr(left, right):
    pair = pd.concat([left, right], axis=1).dropna()
    if len(pair) < 3 or pair.iloc[:, 0].std() == 0 or pair.iloc[:, 1].std() == 0:
        return np.nan
    return float(pair.iloc[:, 0].corr(pair.iloc[:, 1]))


def find_best_lag(df, timestep_minutes, max_lag_minutes):
    """Return the timing offset with the strongest target/actual correlation.

    Positive offsets mean actual response lags the target. Negative offsets
    mean actual appears to lead the target.
    """
    max_steps = max(0, int(round(max_lag_minutes / timestep_minutes)))
    target = df["Target Delta (kW)"]
    actual = df["Actual HPWH Delta (kW)"]
    candidates = []
    for lag_steps in range(-max_steps, max_steps + 1):
        corr = safe_corr(target.shift(lag_steps), actual)
        candidates.append(
            {
                "lag_minutes": lag_steps * timestep_minutes,
                "correlation": corr,
            }
        )
    usable = [row for row in candidates if np.isfinite(row["correlation"])]
    best = max(usable, key=lambda row: row["correlation"]) if usable else {
        "lag_minutes": np.nan,
        "correlation": np.nan,
    }
    return best, pd.DataFrame(candidates)


def boolean_series(series):
    """Coerce common CSV boolean representations."""
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    return (
        series.astype(str)
        .str.strip()
        .str.lower()
        .isin({"true", "1", "yes", "y"})
    )


def action_response_estimate(df, count_column, expected_sign):
    """Estimate same-step kW response per device for isolated action rows."""
    action_columns = [
        "Units Added to LOAD",
        "Units Released from LOAD",
        "Units Added to SHED",
        "Units Released from SHED",
    ]
    if count_column not in df or not set(action_columns).issubset(df.columns):
        return {"samples": 0, "median_kw": np.nan, "p10_kw": np.nan, "p90_kw": np.nan}

    actual_change = df["Actual HPWH Delta (kW)"].diff()
    isolated = df[count_column].fillna(0) > 0
    for other in action_columns:
        if other != count_column:
            isolated &= df[other].fillna(0) == 0

    per_unit = expected_sign * actual_change[isolated] / df.loc[isolated, count_column]
    per_unit = per_unit.replace([np.inf, -np.inf], np.nan).dropna()
    # Negative estimates usually indicate that baseline noise or rebound was
    # larger than the commanded action; exclude them from device-power tuning.
    per_unit = per_unit[per_unit > 0]
    return {
        "samples": int(len(per_unit)),
        "median_kw": safe_percentile(per_unit, 50),
        "p10_kw": safe_percentile(per_unit, 10),
        "p90_kw": safe_percentile(per_unit, 90),
    }


def add_metric(rows, category, metric, value, unit="", interpretation=""):
    rows.append(
        {
            "Category": category,
            "Metric": metric,
            "Value": value,
            "Unit": unit,
            "Interpretation": interpretation,
        }
    )


def analyze_controller(df, timestep_minutes, settings, capacity_percentile, max_lag_minutes):
    """Calculate tuning metrics, recommendations, and supporting lag data."""
    rows = []
    recommendations = []
    target = df["Target Delta (kW)"]
    actual = df["Actual HPWH Delta (kW)"]
    error = df["Calculated Tracking Error (kW)"]
    capacity = df["Committed Capacity Used by C0 (kW)"]
    capacity_median = safe_percentile(capacity, 50)

    same_step_corr = safe_corr(target, actual)
    best_lag, lag_table = find_best_lag(
        df,
        timestep_minutes,
        max_lag_minutes,
    )
    mae_kw = safe_mean(error.abs())
    rmse_kw = float(np.sqrt(safe_mean(error ** 2)))
    bias_kw = safe_mean(actual - target)
    normalized_mae = mae_kw / capacity_median if capacity_median > 0 else np.nan

    add_metric(rows, "Run", "Samples", len(df), "rows")
    add_metric(rows, "Run", "Timestep", timestep_minutes, "minutes")
    add_metric(rows, "Run", "Committed capacity", capacity_median, "kW")
    add_metric(rows, "Tracking", "MAE", mae_kw, "kW", "Lower is better")
    add_metric(rows, "Tracking", "Normalized MAE", normalized_mae, "fraction", "MAE divided by committed capacity")
    add_metric(rows, "Tracking", "RMSE", rmse_kw, "kW", "Penalizes large excursions")
    add_metric(rows, "Tracking", "Bias", bias_kw, "kW", "Positive means the fleet tends to consume too much")
    add_metric(rows, "Tracking", "Same-step correlation", same_step_corr, "correlation")
    add_metric(
        rows,
        "Tracking",
        "Best response timing offset",
        best_lag["lag_minutes"],
        "minutes",
        "Positive means actual lags target; negative means actual appears to lead",
    )
    add_metric(rows, "Tracking", "Best lagged correlation", best_lag["correlation"], "correlation")

    for label, mask in [
        ("LOAD request", target > 0),
        ("SHED request", target < 0),
    ]:
        if mask.any():
            add_metric(rows, "Direction", f"{label} MAE", safe_mean(error[mask].abs()), "kW")
            add_metric(rows, "Direction", f"{label} bias", safe_mean((actual - target)[mask]), "kW")

    target_ramp_p95 = safe_percentile(df["Target Ramp (kW/min)"].abs(), 95)
    actual_ramp_p95 = safe_percentile(df["Actual Ramp (kW/min)"].abs(), 95)
    add_metric(rows, "Dynamics", "Absolute target ramp p95", target_ramp_p95, "kW/min")
    add_metric(rows, "Dynamics", "Absolute actual ramp p95", actual_ramp_p95, "kW/min")

    if "Controller Saturated" in df:
        saturation_rate = float(boolean_series(df["Controller Saturated"]).mean())
        add_metric(rows, "Limits", "Controller saturation rate", saturation_rate, "fraction")
    else:
        saturation_rate = np.nan

    suggested_capacity = np.nan
    if {
        "Available Up Capacity (kW)",
        "Available Down Capacity (kW)",
    }.issubset(df.columns):
        needs_up = target >= actual
        needs_down = target < actual
        up_reliable = safe_percentile(
            df.loc[needs_up, "Available Up Capacity (kW)"],
            capacity_percentile,
        )
        down_reliable = safe_percentile(
            df.loc[needs_down, "Available Down Capacity (kW)"],
            capacity_percentile,
        )
        suggested_capacity = min(up_reliable, down_reliable)
        add_metric(rows, "Capacity", f"Up capacity p{capacity_percentile:g}", up_reliable, "kW")
        add_metric(rows, "Capacity", f"Down capacity p{capacity_percentile:g}", down_reliable, "kW")
        add_metric(
            rows,
            "Capacity",
            "Suggested conservative bidirectional capacity",
            suggested_capacity,
            "kW",
            "Minimum of directional capacity percentiles; confirm with a baseline calibration run",
        )
    elif "Baseline HPWH Fleet Power (kW)" in df:
        baseline_bound = safe_percentile(
            df["Baseline HPWH Fleet Power (kW)"],
            capacity_percentile,
        )
        add_metric(
            rows,
            "Capacity",
            f"Baseline downward-power upper bound p{capacity_percentile:g}",
            baseline_bound,
            "kW",
            "Actual shed capability cannot exceed contemporaneous baseline HPWH power",
        )

    action_specs = [
        ("Units Added to LOAD", 1, "Added LOAD response per unit"),
        ("Units Added to SHED", -1, "Added SHED response per unit"),
        ("Units Released from LOAD", -1, "Released LOAD response per unit"),
        ("Units Released from SHED", 1, "Released SHED response per unit"),
    ]
    action_estimates = {}
    for column, sign, label in action_specs:
        estimate = action_response_estimate(df, column, sign)
        action_estimates[column] = estimate
        add_metric(rows, "Actions", f"{label} samples", estimate["samples"], "rows")
        add_metric(rows, "Actions", f"{label} median", estimate["median_kw"], "kW/unit")

    action_columns = [column for column, _, _ in action_specs if column in df]
    if action_columns:
        total_actions = df[action_columns].fillna(0).sum(axis=1)
        action_p95 = safe_percentile(total_actions, 95)
        add_metric(rows, "Actions", "Command changes per interval p95", action_p95, "units")
    if {"Units in LOAD", "Units in SHED"}.issubset(df.columns):
        opposing_fraction = float(
            ((df["Units in LOAD"] > 0) & (df["Units in SHED"] > 0)).mean()
        )
        add_metric(rows, "Actions", "Simultaneous LOAD and SHED", opposing_fraction, "fraction")
    else:
        opposing_fraction = np.nan

    configured_capacity = settings.get("COMMITTED_REGULATION_CAPACITY_KW", capacity_median)
    configured_gain = settings.get("FEEDBACK_GAIN", np.nan)
    configured_ramp = settings.get("MAX_RESPONSE_CHANGE_KW_PER_INTERVAL", np.nan)
    configured_power = settings.get("EXPECTED_ON_POWER_KW", np.nan)
    updated_controller_log = {
        "Available Up Capacity (kW)",
        "Available Down Capacity (kW)",
        "Feedback Error (kW)",
        "Applied Adjustment (kW)",
        "Controller Saturated",
    }.issubset(df.columns)

    if (
        np.isfinite(capacity_median)
        and np.isfinite(configured_capacity)
        and not np.isclose(capacity_median, configured_capacity)
    ):
        recommendations.append(
            f"Run version: this log used {capacity_median:g} kW, while the current B2 setting is "
            f"{configured_capacity:g} kW. Treat controller recommendations from this log as historical."
        )

    if np.isfinite(suggested_capacity) and suggested_capacity > 0:
        if configured_capacity > 1.1 * suggested_capacity:
            recommendations.append(
                f"Capacity: reduce the {configured_capacity:g} kW commitment toward "
                f"{suggested_capacity:.2f} kW, then verify it with a no-regulation baseline run."
            )
        else:
            recommendations.append(
                f"Capacity: the {configured_capacity:g} kW commitment is within the "
                f"observed p{capacity_percentile:g} directional capability ({suggested_capacity:.2f} kW)."
            )
    else:
        recommendations.append(
            "Capacity: run the updated B2 controller to populate directional capacity columns before choosing a final commitment."
        )

    if np.isfinite(saturation_rate) and saturation_rate > 0.10:
        recommendations.append(
            f"Limits: the controller was saturated for {saturation_rate:.1%} of intervals. "
            "Reduce committed capacity or increase capability before increasing feedback gain."
        )

    if not updated_controller_log:
        recommendations.append(
            "Feedback and holds: rerun the updated B2 controller before changing gain, ramp limit, or hold duration; this log lacks the new action and saturation evidence."
        )
    elif np.isfinite(best_lag["lag_minutes"]) and best_lag["lag_minutes"] >= 2 * timestep_minutes:
        if np.isfinite(saturation_rate) and saturation_rate <= 0.10:
            recommendations.append(
                f"Feedback: response is best aligned about {best_lag['lag_minutes']:.1f} minutes late. "
                f"If the response is smooth, test a modest increase from gain {configured_gain:g}."
            )
        else:
            recommendations.append(
                f"Feedback: the apparent {best_lag['lag_minutes']:.1f}-minute lag should not be tuned with gain until saturation is reduced."
            )
    elif np.isfinite(best_lag["lag_minutes"]) and best_lag["lag_minutes"] <= -2 * timestep_minutes:
        recommendations.append(
            f"Timing: actual appears to lead target by {-best_lag['lag_minutes']:.1f} minutes. "
            "Check timestamp alignment and controlled-versus-baseline thermal-state effects before increasing gain."
        )
    elif np.isfinite(same_step_corr):
        recommendations.append(
            "Feedback: same-step alignment is reasonably close to the best lag; retain the current gain unless the tuning plot shows oscillation."
        )

    if updated_controller_log and np.isfinite(configured_ramp) and np.isfinite(target_ramp_p95):
        if configured_ramp < target_ramp_p95:
            recommendations.append(
                f"Ramp: the {configured_ramp:g} kW/interval limit is below the p95 target ramp "
                f"of {target_ramp_p95:.2f} kW/min. Increase it cautiously only after capacity saturation is controlled."
            )
        elif actual_ramp_p95 > 1.5 * max(target_ramp_p95, 0.01):
            recommendations.append(
                "Ramp: actual response changes substantially faster than the target; consider lowering the response-change limit."
            )

    load_estimate = action_estimates["Units Added to LOAD"]
    if load_estimate["samples"] >= 5 and np.isfinite(load_estimate["median_kw"]):
        if not np.isfinite(configured_power) or abs(load_estimate["median_kw"] - configured_power) > 0.2 * configured_power:
            recommendations.append(
                f"Power estimate: isolated LOAD actions imply about {load_estimate['median_kw']:.3f} kW/unit "
                f"versus the configured {configured_power:g} kW. Confirm the distribution before updating EXPECTED_ON_POWER_KW."
            )
    else:
        recommendations.append(
            "Power estimate: fewer than five isolated LOAD-action rows were available, so EXPECTED_ON_POWER_KW was not recalibrated."
        )

    if np.isfinite(opposing_fraction) and opposing_fraction > 0.10:
        recommendations.append(
            f"Holds: LOAD and SHED commands overlapped for {opposing_fraction:.1%} of intervals. "
            "Inspect hold duration and the release-first action counts before shortening holds."
        )

    return pd.DataFrame(rows), recommendations, lag_table


def make_tuning_plot(df, output_path):
    """Save a compact four-panel controller tuning dashboard."""
    if plt is None or mdates is None:
        return False

    fig, axes = plt.subplots(4, 1, figsize=(13, 11), sharex=True)
    time = df["Time"]

    axes[0].plot(time, df["Target Delta (kW)"], label="Target", color="purple")
    axes[0].plot(time, df["Actual HPWH Delta (kW)"], label="Actual", color="green")
    if "Capacity-Limited Target (kW)" in df:
        axes[0].plot(
            time,
            df["Capacity-Limited Target (kW)"],
            label="Capacity-limited target",
            color="darkorange",
            linestyle="--",
        )
    axes[0].axhline(0, color="black", linewidth=0.8)
    axes[0].set_ylabel("Response (kW)")
    axes[0].legend(loc="upper right", ncol=3)
    axes[0].set_title("HPWH Controller Tuning Dashboard")

    axes[1].plot(
        time,
        df["Calculated Tracking Error (kW)"],
        color="firebrick",
        label="Target - actual",
    )
    axes[1].axhline(0, color="black", linewidth=0.8)
    axes[1].set_ylabel("Error (kW)")
    axes[1].legend(loc="upper right")

    if {
        "Available Up Capacity (kW)",
        "Available Down Capacity (kW)",
    }.issubset(df.columns):
        axes[2].plot(time, df["Available Up Capacity (kW)"], label="Available up")
        axes[2].plot(time, df["Available Down Capacity (kW)"], label="Available down")
        if df["Committed Capacity Used by C0 (kW)"].notna().any():
            axes[2].plot(
                time,
                df["Committed Capacity Used by C0 (kW)"],
                label="Committed",
                color="black",
                linestyle=":",
            )
        axes[2].set_ylabel("Capacity (kW)")
        axes[2].legend(loc="upper right", ncol=3)
    elif {
        "Baseline HPWH Fleet Power (kW)",
        "Controlled HPWH Fleet Power (kW)",
    }.issubset(df.columns):
        axes[2].plot(time, df["Baseline HPWH Fleet Power (kW)"], label="Baseline HPWH")
        axes[2].plot(time, df["Controlled HPWH Fleet Power (kW)"], label="Controlled HPWH")
        axes[2].set_ylabel("Fleet power (kW)")
        axes[2].legend(loc="upper right")
    else:
        axes[2].text(0.5, 0.5, "Capacity fields unavailable", ha="center", va="center", transform=axes[2].transAxes)

    if {"Units in LOAD", "Units in SHED"}.issubset(df.columns):
        axes[3].plot(time, df["Units in LOAD"], label="LOAD", color="darkorange")
        axes[3].plot(time, df["Units in SHED"], label="SHED", color="steelblue")
        axes[3].set_ylabel("Commanded units")
        axes[3].legend(loc="upper right")
    elif "Applied Adjustment (kW)" in df:
        axes[3].plot(time, df["Applied Adjustment (kW)"], label="Applied adjustment")
        axes[3].set_ylabel("Adjustment (kW)")
        axes[3].legend(loc="upper right")
    else:
        axes[3].text(0.5, 0.5, "Command fields unavailable", ha="center", va="center", transform=axes[3].transAxes)

    axes[3].set_xlabel("Time")
    axes[3].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return True


def format_value(value):
    if pd.isna(value):
        return "not available"
    if isinstance(value, (int, np.integer)):
        return str(value)
    if isinstance(value, (float, np.floating)):
        return f"{value:.4g}"
    return str(value)


def write_text_report(path, run_id, source_path, settings, summary, recommendations, missing_new_columns):
    lines = [
        f"HPWH controller tuning report: {run_id}",
        f"Source: {source_path}",
        "",
        "Controller settings found in HPWH_B2.py",
    ]
    if settings:
        for key in sorted(settings):
            lines.append(f"  {key}: {settings[key]}")
    else:
        lines.append("  No literal controller settings were found.")

    lines.extend(["", "Key metrics"])
    for row in summary.itertuples(index=False):
        unit = f" {row.Unit}" if row.Unit else ""
        lines.append(f"  [{row.Category}] {row.Metric}: {format_value(row.Value)}{unit}")

    lines.extend(["", "Recommended next steps"])
    for index, recommendation in enumerate(recommendations, start=1):
        lines.append(f"  {index}. {recommendation}")

    if missing_new_columns:
        lines.extend(
            [
                "",
                "Unavailable diagnostics",
                "  This log predates some updated B2 tuning fields:",
                "  " + ", ".join(missing_new_columns),
                "  Run the updated HPWH_B2.py to populate them.",
            ]
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(run_id, vpp_log=None, output_dir=None, capacity_percentile=DEFAULT_CAPACITY_PERCENTILE, max_lag_minutes=DEFAULT_MAX_LAG_MINUTES):
    if not 0 <= capacity_percentile <= 100:
        raise ValueError("capacity_percentile must be between 0 and 100.")
    if max_lag_minutes < 0:
        raise ValueError("max_lag_minutes must be non-negative.")

    vpp_path = find_vpp_log(run_id, vpp_log)
    df, timestep_minutes = load_vpp_data(vpp_path)
    settings = read_controller_settings()
    summary, recommendations, lag_table = analyze_controller(
        df,
        timestep_minutes,
        settings,
        capacity_percentile,
        max_lag_minutes,
    )

    destination = Path(output_dir).expanduser().resolve() if output_dir else SCRIPT_DIR / "Ready_data" / run_id
    destination.mkdir(parents=True, exist_ok=True)

    summary_path = destination / f"{run_id}_controller_tuning_summary.csv"
    timeseries_path = destination / f"{run_id}_controller_tuning_timeseries.csv"
    lag_path = destination / f"{run_id}_controller_tuning_lag_scan.csv"
    report_path = destination / f"{run_id}_controller_tuning_report.txt"
    plot_path = destination / f"{run_id}_controller_tuning_plot.png"

    summary.to_csv(summary_path, index=False)
    derived_columns = [
        "Time",
        "Target Delta (kW)",
        "Actual HPWH Delta (kW)",
        "Calculated Tracking Error (kW)",
        "Absolute Tracking Error (kW)",
        "Normalized Tracking Error",
        "Target Ramp (kW/min)",
        "Actual Ramp (kW/min)",
    ]
    optional_columns = [
        "Capacity-Limited Target (kW)",
        "Feedback Error (kW)",
        "Requested Adjustment (kW)",
        "Applied Adjustment (kW)",
        "Available Up Capacity (kW)",
        "Available Down Capacity (kW)",
        "Controller Saturated",
        "Units in LOAD",
        "Units in SHED",
        "Units Added to LOAD",
        "Units Released from LOAD",
        "Units Added to SHED",
        "Units Released from SHED",
    ]
    df[[*derived_columns, *[column for column in optional_columns if column in df]]].to_csv(
        timeseries_path,
        index=False,
    )
    lag_table.to_csv(lag_path, index=False)

    new_columns = {
        "Available Up Capacity (kW)",
        "Available Down Capacity (kW)",
        "Feedback Error (kW)",
        "Applied Adjustment (kW)",
        "Controller Saturated",
        "Units Added to LOAD",
        "Units Released from LOAD",
        "Units Added to SHED",
        "Units Released from SHED",
    }
    missing_new_columns = sorted(new_columns - set(df.columns))
    write_text_report(
        report_path,
        run_id,
        vpp_path,
        settings,
        summary,
        recommendations,
        missing_new_columns,
    )
    plot_created = make_tuning_plot(df, plot_path)

    print(report_path.read_text(encoding="utf-8"))
    print("Created:")
    created_paths = [report_path, summary_path, timeseries_path, lag_path]
    if plot_created:
        created_paths.append(plot_path)
    else:
        print("  Plot skipped because matplotlib is not installed.")
    for path in created_paths:
        print(f"  {path}")

    return {
        "report": report_path,
        "summary": summary_path,
        "timeseries": timeseries_path,
        "lag_scan": lag_path,
        "plot": plot_path if plot_created else None,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Analyze an HPWH B2 fleet log for controller tuning.",
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--vpp-log")
    parser.add_argument("--output-dir")
    parser.add_argument(
        "--capacity-percentile",
        type=float,
        default=DEFAULT_CAPACITY_PERCENTILE,
    )
    parser.add_argument(
        "--max-lag-minutes",
        type=float,
        default=DEFAULT_MAX_LAG_MINUTES,
    )
    args = parser.parse_args()
    main(
        run_id=args.run_id,
        vpp_log=args.vpp_log,
        output_dir=args.output_dir,
        capacity_percentile=args.capacity_percentile,
        max_lag_minutes=args.max_lag_minutes,
    )
