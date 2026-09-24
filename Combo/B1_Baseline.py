# -*- coding: utf-8 -*-
"""
Created on Wed Sep  3 17:39:26 2025
Modified on Nov 19 2025
Modified on Aug 25 2026

@author: danap
@edited by: jdinsmor
@edited by: t-metzler 
"""

import os
import datetime as dt
import pandas as pd
from ochre.utils.schedule import ALL_SCHEDULE_NAMES
import concurrent.futures
from pathlib import Path
import numpy as np
import json
import hashlib
import uuid
import copy
from itertools import repeat


# Settings and reusable setup are owned by B_Common.
# B1 runs NORMAL operation and exports a reusable baseline and capacity estimates.
try:
    from . import B_Common as common
    from .B_ControlSignals import control_for_home
except ImportError:
    import B_Common as common
    from B_ControlSignals import control_for_home

CONFIG = common.load_configuration()
# create_home_schedule = common.create_home_schedule
count = 0

#########################################
# SCHEDULE FILTERING
#########################################

def restore_time_column(df, result_name):
    """Move OCHRE's datetime index into a regular Time column."""
    if "Time" in df.columns:
        return df

    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError(
            f"{result_name} has no Time column and its index is not datetime."
        )

    return df.rename_axis("Time").reset_index()

def prepare_schedules(home_path):
    """Filter normal schedules without changing cadence or inventing EV availability."""
    source = Path(home_path) / CONFIG["CSV_ADDRESS"]
    target = Path(home_path) / 'baseline_schedules.csv'
    frame = pd.read_csv(source)
    valid = set(ALL_SCHEDULE_NAMES)
    # OCHRE indexes every input column in ALL_SCHEDULE_NAMES. Name-based
    # exceptions (e.g. electric_vehicle_charging) cause KeyError in versions
    # that generate EV driving/charging events internally.
    columns = [c for c in frame if c in valid]
    if not columns:
        raise ValueError(f"No recognized schedules in {source}")
    frame[columns].to_csv(target, index=False)
    return str(target)


def init_fleet_worker(home):
    """Initialize one dwelling and report success or failure."""
    # Baseline uses default controls without regulation overrides.
    device_modes = {}

    if CONFIG["WH_SIMULATION"] == "ON":
        device_modes["WH"] = "NORMAL"

    if CONFIG["HVAC_SIMULATION"] == "ON":
        device_modes["HVAC"] = "NORMAL"

    if CONFIG["EV_SIMULATION"] == "ON":
        device_modes["EV"] = "NORMAL"

    if CONFIG["BATTERY_SIMULATION"] == "ON":
        device_modes["Battery"] = "NORMAL"

    if CONFIG["DRYER_SIMULATION"] == "ON":
        device_modes["Dryer"] = "NORMAL"


    try:
        base_dw, home_info = common.init_home(
            home,
            CONFIG,
            prepare_schedules(home),
            run_kind="baseline"
        )

        return {
            "success": True,
            "base": base_dw,
            "path": home,
            "last_base_kw": 0.0,
            "home_info": home_info,
            "device_modes": device_modes,
        }

    except Exception as e:
        return {
            "success": False,
            "path": home,
            "error": repr(e),
        }

#########################################
# FIND ALL HOMES
#########################################

def find_all_homes(base_dir):
    homes = []
    for item in sorted(os.listdir(base_dir)):
        home_path = os.path.join(base_dir, item)
        if os.path.isdir(home_path):
            # Only add folders with required files
            if os.path.isfile(os.path.join(home_path, CONFIG["XML_ADDRESS"])) and \
               os.path.isfile(os.path.join(home_path, CONFIG["CSV_ADDRESS"])):
                homes.append(home_path)
    return homes


def validate_results(frame, expected_times, label, required_columns):
    frame = restore_time_column(frame, label).copy()
    frame["Time"] = pd.to_datetime(frame["Time"], errors="raise")
    if not pd.DatetimeIndex(frame["Time"]).equals(pd.DatetimeIndex(expected_times)):
        raise ValueError(f"{label}: timestamps do not match the simulation grid")
    for column in required_columns:
        if column not in frame:
            raise ValueError(f"{label}: missing {column}")
        frame[column] = pd.to_numeric(frame[column], errors="raise")
        if not np.isfinite(frame[column]).all():
            raise ValueError(f"{label}: nonfinite {column}")
    return frame


def aggregate_results(homes, work_dir, expected_times, required_by_home):
    """Read only this run's outputs; never silently skip missing homes."""
    if not homes:
        raise ValueError("Cannot aggregate an empty fleet")
    frames = []
    for home in homes:
        name = Path(home).name
        source = Path(work_dir) / "homes" / name / "home_baseline.csv"
        if not source.is_file():
            raise FileNotFoundError(source)
        frame = validate_results(pd.read_csv(source), expected_times, name,
                                 required_by_home[name])
        frame["Home"] = name
        frames.append(frame)
    output = Path(work_dir) / "baseline.csv"
    pd.concat(frames, ignore_index=True).to_csv(output, index=False)
    return str(output)


def update_home_worker(home_data, sim_time):
    """Advance one normal dwelling and read real, present equipment states."""
    try:
        home_data["sim_time"] = sim_time
        dwelling = home_data["base"]
        if dwelling.current_time != sim_time:
            raise ValueError(f"Dwelling time {dwelling.current_time} != {sim_time}")
        control = control_for_home(home_data, CONFIG, sim_time, baseline=True)
        metrics = dwelling.update(control_signal=control)
        if not isinstance(metrics, dict):
            metrics = dwelling.current_results
        power = _capacity_number(metrics.get("Total Electric Power (kW)"))
        if power is None:
            raise ValueError("Missing/nonfinite Total Electric Power (kW)")
        devices = {}
        for name, equipment in dwelling.equipment.items():
            if equipment.end_use not in common.FLEX_END_USES:
                continue
            device_power = _capacity_number(equipment.electric_kw)
            if device_power is None:
                raise ValueError(f"Invalid power for {name}")
            state = {"end_use": equipment.end_use, "electric_kw": device_power,
                     "mode": getattr(equipment, "mode", None)}
            if equipment.end_use == "Water Heating":
                model = getattr(equipment, "model", None)
                if model is not None:
                    temperatures = np.asarray(model.states, dtype=float)
                    if not np.isfinite(temperatures).all():
                        raise ValueError(f"Invalid tank temperatures for {name}")
                    state["tank_temperatures_c"] = temperatures.tolist()
            if equipment.end_use in ("HVAC Heating", "HVAC Cooling"):
                value = _capacity_number(equipment.zone.temperature)
                if value is None:
                    raise ValueError(f"Invalid indoor temperature for {name}")
                state["indoor_temperature_c"] = value
            if equipment.end_use in ("EV", "Battery"):
                value = _capacity_number(equipment.soc)
                if value is None or not -0.001 <= value <= 1.001:
                    raise ValueError(f"Invalid SOC for {name}")
                state["soc"] = value
            if hasattr(equipment, "in_event"):
                state["in_event"] = bool(equipment.in_event)
            devices[name] = state
        return {"success": True, "base_kw": power, "devices": devices}
    except Exception as exc:
        return {"success": False, "path": home_data["path"], "error": repr(exc)}


def _capacity_number(value):
    """Return a finite float, or None when a required measurement is absent."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if np.isfinite(value) else None


def estimate_wh_regulation_capacity_kw(home, wh, settings=None):
    """Approximate LU/S headroom (kW), without changing the water heater.

    Uses conservative node-temperature checks for the existing setpoint-only
    commands. This is not guaranteed response or a sustained-energy estimate.
    """
    settings = CONFIG if settings is None else settings
    power = _capacity_number(getattr(wh, "electric_kw", None))
    model = getattr(wh, "model", None)
    temps = np.asarray(getattr(model, "states", []), dtype=float)
    if power is None or not temps.size or not np.isfinite(temps).all():
        return 0.0, 0.0
    if not getattr(wh, "is_electric", False) or getattr(wh, "is_gas", False):
        return 0.0, 0.0

    load_sp = _capacity_number(settings.get("WH_Tcontrol_LOADC"))
    load_db = _capacity_number(settings.get("WH_Tcontrol_LOADdeadbandC"))
    shed_sp = _capacity_number(settings.get("WH_Tcontrol_SHEDC"))
    if None in (load_sp, load_db, shed_sp):
        return 0.0, 0.0
    power = max(0.0, power)
    up = 0.0
    if hasattr(wh, "hp_capacity") and not getattr(wh, "er_only_mode", False):
        capacity = _capacity_number(wh.hp_capacity)
        efficiency = _capacity_number(getattr(wh, "hp_cop", None))
        auxiliary = _capacity_number(getattr(wh, "fan_power", 0.0))
    else:
        capacity = _capacity_number(getattr(wh, "capacity_rated", None))
        efficiency = _capacity_number(getattr(wh, "efficiency", None))
        auxiliary = 0.0
    if (capacity is not None and efficiency is not None and efficiency > 0
            and auxiliary is not None and temps.max() < load_sp - load_db):
        on_kw = (capacity / efficiency + auxiliary) / 1000
        up = max(0.0, on_kw - power)
    # S changes the thermostat; it does not force Load Fraction to zero.
    down = power if temps.min() > shed_sp else 0.0
    return up, down


def _estimate_hvac_capacity_kw(home, equipment, settings, heating):
    """Approximate LU/S headroom from thermostat thresholds and current rating."""
    power = _capacity_number(getattr(equipment, "electric_kw", None))
    temperature = _capacity_number(getattr(getattr(equipment, "zone", None), "temperature", None))
    if power is None or temperature is None or getattr(equipment, "is_gas", False):
        return 0.0, 0.0
    sim_time = home.get("sim_time")
    if sim_time is None:
        sim_time = getattr(home.get("base"), "current_time", None)
    if sim_time is None:
        return 0.0, 0.0
    if heating == (sim_time.month in [5, 6, 7, 8, 9]):
        return 0.0, 0.0  # Match determine_control's seasonal policy.
    prefix = "HEAT" if heating else "AC"
    load_sp = _capacity_number(settings.get(prefix + "_Tcontrol_LOADC"))
    load_db = _capacity_number(settings.get(prefix + "_Tcontrol_LOADdeadbandC"))
    shed_sp = _capacity_number(settings.get(prefix + "_Tcontrol_SHEDC"))
    shed_db = _capacity_number(settings.get(prefix + "_Tcontrol_deadbandC"))
    offset = _capacity_number(getattr(equipment, "deadband_offset", None))
    if None in (load_sp, load_db, shed_sp, shed_db, offset):
        return 0.0, 0.0
    direction = 1 if heating else -1
    turn_on = load_sp - direction * load_db * (1 - offset)
    turn_off = shed_sp + direction * shed_db * offset
    power = max(0.0, power)
    up = 0.0
    capacity = _capacity_number(getattr(equipment, "capacity_max", None))
    eir = _capacity_number(getattr(equipment, "eir_max", None))
    fan = _capacity_number(getattr(equipment, "fan_power_max", None))
    if (None not in (capacity, eir, fan)
            and direction * (temperature - turn_on) < 0):
        up = max(0.0, (capacity * eir + fan) / 1000 - power)
    down = power if direction * (temperature - turn_off) > 0 else 0.0
    return up, down


def estimate_heat_regulation_capacity_kw(home, heater, settings=None):
    return _estimate_hvac_capacity_kw(home, heater, CONFIG if settings is None else settings, True)


def estimate_ac_regulation_capacity_kw(home, ac, settings=None):
    return _estimate_hvac_capacity_kw(home, ac, CONFIG if settings is None else settings, False)


def estimate_dryer_regulation_capacity_kw(home, dryer, settings=None):
    """No implemented dryer mode changes power in B_ControlSignals yet."""
    return 0.0, 0.0


def estimate_ev_regulation_capacity_kw(home, ev, settings=None):
    """Shed charging to the S power ceiling; LU equals NORMAL in the translator.

    Charging deadlines are not modeled here: this is instantaneous headroom.
    """
    settings = CONFIG if settings is None else settings
    power = _capacity_number(getattr(ev, "electric_kw", None))
    charger = _capacity_number(home.get("home_info", {}).get("home_charger_kw"))
    fraction = _capacity_number(settings.get("EV_SHED_PCT"))
    if (power is None or charger is None or charger <= 0
            or fraction is None or not 0 <= fraction <= 1
            or not getattr(ev, "in_event", False)):
        return 0.0, 0.0
    shed_limit = max(fraction * charger, 0.001)
    return 0.0, max(0.0, power - shed_limit)


def estimate_battery_regulation_capacity_kw(home, battery, settings=None):
    """Signed AC headroom for LU/S, limited by OCHRE's timestep SOC/efficiency limits."""
    settings = CONFIG if settings is None else settings
    power = _capacity_number(getattr(battery, "electric_kw", None))
    load = _capacity_number(settings.get("P_Battery_LU_KW"))
    shed = _capacity_number(settings.get("P_Battery_SHED_KW"))
    if None in (power, load, shed):
        return 0.0, 0.0
    # OCHRE may update efficiency_internal while calculating limits; isolate it.
    low, high = copy.copy(battery).get_power_limits()
    low, high = _capacity_number(low), _capacity_number(high)
    if low is None or high is None or low > high:
        return 0.0, 0.0
    load_power = min(high, max(low, load))
    shed_power = min(high, max(low, shed))
    return max(0.0, load_power - power), max(0.0, power - shed_power)


def estimate_baseline_regulation_capacity_kw(fleet_data, settings=None, return_details=False):
    """Sum instantaneous LU/S estimates for enabled equipment actually present.

    Positive/up means increased consumption. Returns (up_kw, down_kw).
    Thermal estimates omit cycling delays, future draws and sustained service;
    B2 must recheck eligibility at dispatch. No equipment state is mutated.
    """
    settings = CONFIG if settings is None else settings
    device_map = {
        "Water Heating": ("WH_SIMULATION", estimate_wh_regulation_capacity_kw),
        "HVAC Heating": ("HVAC_SIMULATION", estimate_heat_regulation_capacity_kw),
        "HVAC Cooling": ("HVAC_SIMULATION", estimate_ac_regulation_capacity_kw),
        "Clothes Dryer": ("DRYER_SIMULATION", estimate_dryer_regulation_capacity_kw),
        "EV": ("EV_SIMULATION", estimate_ev_regulation_capacity_kw),
        "Battery": ("BATTERY_SIMULATION", estimate_battery_regulation_capacity_kw),
    }
    available_up_kw = available_down_kw = 0.0
    details = {end_use: {"up_kw": 0.0, "down_kw": 0.0} for end_use in device_map}
    for home in fleet_data:
        for equipment in home["base"].equipment.values():
            entry = device_map.get(equipment.end_use)
            if entry is None or not equipment.is_electric:
                continue
            flag, estimate = entry
            if settings.get(flag, "OFF") != "ON":
                continue
            up, down = estimate(home, equipment, settings)
            if not np.isfinite([up, down]).all() or min(up, down) < 0:
                raise ValueError(f"Invalid capacity for {equipment.name}")
            available_up_kw += up
            available_down_kw += down
            details[equipment.end_use]["up_kw"] += up
            details[equipment.end_use]["down_kw"] += down
    if return_details:
        return available_up_kw, available_down_kw, details
    return available_up_kw, available_down_kw

#########################################
# MAIN EXECUTION
#########################################
def _file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run_baseline(run_dir, manifest):
    homes = find_all_homes(CONFIG["INPUT_DIR"])
    if not homes:
        raise RuntimeError(f"No valid homes in {CONFIG['INPUT_DIR']}")
    # No example homes are copied into the selected fleet.
    if not Path(CONFIG["WEATHER_FILE"]).is_file():
        raise FileNotFoundError(CONFIG["WEATHER_FILE"])
    manifest["weather_sha256"] = _file_hash(CONFIG["WEATHER_FILE"])
    manifest["homes"] = []
    manifest["initialization_failures"] = []
    manifest["homes_requested"] = len(homes)
    minimum_homes = CONFIG["MIN_INITIALIZED_HOMES"]
    failure_limit = len(homes) - minimum_homes
    manifest["minimum_initialized_homes"] = minimum_homes
    manifest["initialization_failure_limit"] = failure_limit
    if failure_limit <= 0:
        raise RuntimeError(f"Initialization canceled: {len(homes)} homes available; "
                           f"the configured rule requires more than {minimum_homes} successful homes")
    fleet_data = []
    print(f"Initializing {len(homes)} homes serially...", flush=True)
    for i, home in enumerate(homes, 1):
        result = init_fleet_worker(home)
        if not result["success"]:
            manifest["initialization_failures"].append({"path": str(Path(home).resolve()), "error": result["error"]})
            failed_count = len(manifest["initialization_failures"])
            print(f"Skipping {Path(home).name}: {result['error']} "
                  f"({failed_count}/{failure_limit} initialization failures)", flush=True)
            if failed_count > failure_limit:
                raise RuntimeError(f"Initialization canceled: {failed_count} homes failed "
                                   f"(limit {len(homes)} - {minimum_homes} = {failure_limit}). "
                                   f"Last failure: {result['error']}")
            continue
        fleet_data.append(result)
        manifest["homes"].append({
            "name": Path(home).name, "path": str(Path(home).resolve()),
            "xml_sha256": _file_hash(Path(home) / CONFIG["XML_ADDRESS"]),
            "schedule_sha256": _file_hash(Path(home) / CONFIG["CSV_ADDRESS"]),
            "prepared_schedule_sha256": _file_hash(Path(home) / "baseline_schedules.csv"),
            "home_info": result["home_info"],
        })
        if i == 1 or i % 20 == 0 or i == len(homes):
            print(f"Processed {i}/{len(homes)} homes; {len(fleet_data)} initialized", flush=True)
    if not fleet_data:
        raise RuntimeError("No homes initialized successfully; cannot simulate an empty fleet")
    homes = [home["path"] for home in fleet_data]
    print(f"Initialization complete: {len(homes)} successful, "
          f"{len(manifest['initialization_failures'])} skipped", flush=True)
    sim_times = pd.DatetimeIndex(fleet_data[0]["base"].sim_times)
    if sim_times.empty or sim_times.hasnans or not sim_times.is_unique:
        raise ValueError("Invalid simulation time grid")
    expected = pd.date_range(sim_times[0], periods=len(sim_times), freq=dt.timedelta(minutes=CONFIG["t_res"]))
    if not sim_times.equals(expected):
        raise ValueError("Irregular simulation time grid")
    for home in fleet_data:
        if not sim_times.equals(pd.DatetimeIndex(home["base"].sim_times)):
            raise ValueError(f"Mismatched time grid: {home['path']}")
    # WetAppliance uses global random draws during updates. Fail explicitly rather
    # than claim reproducibility for that model under threaded stepping.
    for home in fleet_data:
        if any(type(eq).__module__.endswith("WetAppliance") for eq in home["base"].equipment.values()):
            raise ValueError("WetAppliance requires isolated random generators before threaded baseline updates")
    manifest["time_start"] = str(sim_times[0])
    manifest["time_end"] = str(sim_times[-1])
    manifest["time_steps"] = len(sim_times)
    rows = []
    progress_interval = max(1, round(60 / CONFIG["t_res"]))
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        for step, sim_time in enumerate(sim_times, 1):
            results = list(executor.map(update_home_worker, fleet_data, repeat(sim_time)))
            for home, result in zip(fleet_data, results):
                if not result["success"]:
                    raise RuntimeError(f"Update failed at {sim_time} for {home['path']}: {result['error']}")
                home["last_base_kw"] = result["base_kw"]
                home["devices"] = result["devices"]
            up, down, details = estimate_baseline_regulation_capacity_kw(fleet_data, return_details=True)
            row = {"Time": sim_time, "Up Capacity (kW)": up,
                   "Down Capacity (kW)": down, "Homes": len(fleet_data)}
            for device, values in details.items():
                row[f"{device} Up Capacity (kW)"] = values["up_kw"]
                row[f"{device} Down Capacity (kW)"] = values["down_kw"]
            rows.append(row)
            if step % progress_interval == 0 or step == len(sim_times):
                print(f"Completed {step}/{len(sim_times)} steps", flush=True)
    required_by_home = {}
    for home in fleet_data:
        name = Path(home["path"]).name
        frame, _, _ = home["base"].finalize()
        required = ["Total Electric Power (kW)", "Total Electric Energy (kWh)"]
        for end_use in home["home_info"]["participating_end_uses"]:
            required.append(end_use + " Electric Power (kW)")
        for end_use in ("EV", "Battery"):
            if end_use in home["home_info"]["participating_end_uses"]:
                required.append(end_use + " SOC (-)")
        frame = validate_results(frame, sim_times, name, required)
        # Retain temperatures and other diagnostics in addition to required power.
        destination = run_dir / "homes" / name
        destination.mkdir(parents=True)
        frame.to_csv(destination / "home_baseline.csv", index=False)
        required_by_home[name] = required
    baseline_path = aggregate_results(homes, run_dir, sim_times, required_by_home)
    capacities = pd.DataFrame(rows)
    capacity_path = run_dir / "capacity.csv"
    capacities.to_csv(capacity_path, index=False)
    quantile = float(CONFIG["RELIABLE_CAPACITY_QUANTILE"])
    summary = {
        "homes_simulated": len(homes), "homes_failed": len(manifest["initialization_failures"]),
        "baseline_path": baseline_path, "capacity_path": str(capacity_path),
        "manifest_path": str(run_dir / "manifest.json"),
        "capacity_availability_quantile": quantile,
        "up_regulation_capacity_kw": float(capacities["Up Capacity (kW)"].quantile(quantile)),
        "down_regulation_capacity_kw": float(capacities["Down Capacity (kW)"].quantile(quantile)),
    }
    manifest["summary"] = summary
    return summary


def main():
    minimum_homes = CONFIG["MIN_INITIALIZED_HOMES"]
    if isinstance(minimum_homes, bool) or not isinstance(minimum_homes, int) or minimum_homes < 0:
        raise ValueError("MIN_INITIALIZED_HOMES must be a nonnegative integer")
    quantile = float(CONFIG["RELIABLE_CAPACITY_QUANTILE"])
    if not np.isfinite(quantile) or not 0 <= quantile <= 1:
        raise ValueError("RELIABLE_CAPACITY_QUANTILE must be between 0 and 1")
    run_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    run_dir = Path(CONFIG.get("RESULTS_DIR", Path(__file__).resolve().parent / "Results")) / run_id
    run_dir.mkdir(parents=True)
    manifest = {"run_id": run_id, "status": "running", "configuration": CONFIG,
                "capacity_basis": "Instantaneous LU/S estimates; excludes response delay and sustained-service guarantees"}
    try:
        result = _run_baseline(run_dir, manifest)
        manifest["status"] = "complete"
        print(f"Baseline saved: {result['baseline_path']}", flush=True)
        return result
    except Exception as exc:
        manifest.update(status="failed", error=repr(exc))
        raise
    finally:
        (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
    print("Simulation finished.", flush=True)
