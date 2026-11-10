"""Parse separated B1/B2 exports into per-home time tables.

Run directly for the latest completed pair in Combo/Results, or pass
--run-dir Combo/Results/<run_id>. Outputs go to <run_dir>/Ready_data.
No simulation modules are imported or executed.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

RESULTS_DIR = Path(__file__).resolve().parent / "Results"
RUN_DIR = None  # Set a specific result folder here, or use --run-dir.

# Export suffixes are retained from the original C1/C2 workflow.
METRICS = {
    "Total Electric Power (kW)": ("total_power", "Total household power"),
    "Water Heating Electric Power (kW)": ("WH_power", "Water heating"),
    "HVAC Cooling Electric Power (kW)": ("AC_power", "HVAC cooling"),
    "HVAC Heating Electric Power (kW)": ("HEAT_power", "HVAC heating"),
    "Clothes Dryer Electric Power (kW)": ("Dryer_power", "Clothes dryer"),
    "EV Electric Power (kW)": ("EV_power", "Electric vehicle power"),
    "EV SOC (-)": ("EV_SOC", "Electric vehicle state of charge"),
    "Battery Electric Power (kW)": ("BATT_power", "Battery power"),
    "Battery SOC (-)": ("BATT_SOC", "Battery state of charge"),
}


def baseline_directory(run_dir):
    run_dir = Path(run_dir)
    return run_dir if (run_dir / "manifest.json").is_file() else run_dir.parent


def select_run(run_dir=None):
    """Select a controlled child, latest child of a baseline, or legacy pair."""
    root = Path(run_dir).resolve() if run_dir is not None else RESULTS_DIR
    candidates = list(root.glob("controlled_*/regulation_manifest.json"))
    if run_dir is None:
        candidates += list(root.glob("*/controlled_*/regulation_manifest.json"))
        candidates += list(root.glob("*/regulation_manifest.json"))
    candidates = sorted(candidates, key=lambda p: (p.stat().st_mtime_ns, str(p)), reverse=True)
    if (root / "regulation_manifest.json").is_file():
        candidates.append(root / "regulation_manifest.json")
    for path in candidates:
        candidate = path.parent
        try:
            base_dir = baseline_directory(candidate)
            baseline = json.loads((base_dir / "manifest.json").read_text(encoding="utf-8"))
            controlled = json.loads(path.read_text(encoding="utf-8"))
            if baseline.get("status") != "complete" or controlled.get("status") != "complete":
                continue
            if not baseline.get("run_id") or controlled.get("baseline_run_id") != baseline["run_id"]:
                continue
            if (base_dir / "baseline.csv").is_file() and (candidate / "controlled.csv").is_file():
                return candidate
        except (OSError, ValueError):
            continue
    raise FileNotFoundError(f"No completed B1/B2 pair found in {root}")


def load_results(path):
    """Keep missing device values without discarding valid household samples."""
    frame = pd.read_csv(path, dtype={"Home": str},
                        usecols=lambda name: name in {"Time", "Home", *METRICS})
    required = {"Time", "Home", "Total Electric Power (kW)"}
    if not required.issubset(frame.columns):
        raise ValueError(f"{path}: missing columns {sorted(required - set(frame.columns))}")
    if frame.empty or frame[["Time", "Home"]].isna().any().any():
        raise ValueError(f"{path}: empty results or missing Time/Home")
    frame["Time"] = pd.to_datetime(frame["Time"], errors="raise")
    if frame["Time"].isna().any() or frame.duplicated(["Time", "Home"]).any():
        raise ValueError(f"{path}: missing timestamps or duplicate Time/Home rows")
    metrics = [name for name in METRICS if name in frame]
    frame[metrics] = frame[metrics].apply(pd.to_numeric, errors="raise")
    if np.isinf(frame[metrics].to_numpy()).any():
        raise ValueError(f"{path}: infinite metric values")
    if frame["Total Electric Power (kW)"].isna().any():
        raise ValueError(f"{path}: missing household power values")
    return frame


def parse_run(run_dir):
    run_dir = Path(run_dir)
    frames = {"baseline": load_results(baseline_directory(run_dir) / "baseline.csv"),
              "controlled": load_results(run_dir / "controlled.csv")}
    base, ctrl = frames.values()
    base_keys = pd.MultiIndex.from_frame(base[["Home", "Time"]]).sort_values()
    ctrl_keys = pd.MultiIndex.from_frame(ctrl[["Home", "Time"]]).sort_values()
    if not base_keys.equals(ctrl_keys):
        raise ValueError("Baseline and controlled results have different Home/Time samples")
    output_dir = run_dir / "Ready_data"
    output_dir.mkdir(exist_ok=True)
    tables = {}
    for column, (suffix, _) in METRICS.items():
        available = [column in frame and frame[column].notna().any()
                     for frame in frames.values()]
        if not all(available):
            if any(available):
                print(f"Skipping {column}: no values in one of the two runs.")
            continue
        pair = {}
        for kind, frame in frames.items():
            # Full timestamps preserve day boundaries and sub-minute resolution.
            table = frame.pivot(index="Home", columns="Time", values=column).sort_index(axis=1)
            table.to_csv(output_dir / f"{run_dir.name}_{kind}_{suffix}.csv")
            pair[kind] = table
        tables[column] = pair
    print(f"Per-home tables saved to: {output_dir}")
    return tables


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=RUN_DIR)
    args = parser.parse_args()
    parse_run(select_run(args.run_dir))


if __name__ == "__main__":
    main()
