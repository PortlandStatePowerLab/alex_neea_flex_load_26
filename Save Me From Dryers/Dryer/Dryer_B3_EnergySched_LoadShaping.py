"""
Author: Thomas Metzler
Created: 8/19/26

Adjusts load up and shed commands to keep dryer fleet power consumption at a constant level.
Modified to account for dryer constraints (managing load via SHED and NORMAL restoration only).
Runs an OCHRE baseline, then dispatches dryers using measured whole-home power
from the preceding controlled OCHRE timestep.
"""

import argparse
import math
import os
import shutil
from time import monotonic
import datetime as dt
import pandas as pd
import numpy as np
from ochre import Dwelling
from ochre.Equipment import ScheduledLoad
import concurrent.futures
from pathlib import Path
import ochre
import random

#########################################
# USER SETTINGS
#########################################

filename = 'Dryer_test_Loadshape_17'
Input_folder = "Dryer All Portland Input Files"

# Original OCHRE defaults folder
ochre_dir = Path(ochre.__file__).resolve().parent
DEFAULT_INPUT = ochre_dir / "defaults" / "Input Files"
DEFAULT_WEATHER = ochre_dir / "defaults" / "Weather" / "USA_OR_Portland.Intl.AP.726980_TMY3.epw"

# Safe working folder (writable)
script_dir = os.path.dirname(os.path.abspath(__file__))
fl_dir = os.path.dirname(script_dir)
WORKING_DIR = os.path.dirname(fl_dir)
INPUT_DIR = os.path.join(WORKING_DIR, Input_folder, "bldg")
WEATHER_DIR = os.path.join(WORKING_DIR, "Weather")
WEATHER_FILE = os.path.join(WEATHER_DIR, "USA_OR_Portland.Intl.AP.726980_TMY3.epw")
XML_ADDRESS = "home.xml"
CSV_ADDRESS = "in.schedules.csv"

# Simulation parameters
Start = dt.datetime(2018, 1, 11, 0, 0)
Duration = 2  # days
t_res = 1  # minutes

# --- GLOBAL VPP EVENT SETTINGS ---
VPP_START_TIME = dt.time(12, 0)
VPP_END_TIME = dt.time(23, 0)

# Fleet-agnostic average power targets
AVERAGE_SETPOINT_KW = 2.0     
AVERAGE_DEADBAND_KW = 0.1     
ESTIMATED_SHED_KW = 1.5  

# Duty cycle power fraction during SHED mode
DUTY_CYCLE_FRACTION = 0.25

# --- PID CONTROLLER GAINS ---
KP = 1.0                      
KI = 0.1                      
KD = 0.5                      

#########################################
# HELPER FUNCTIONS
#########################################

def find_all_homes(base_dir):
    homes = []
    for item in os.listdir(base_dir):
        home_path = os.path.join(base_dir, item)
        if os.path.isdir(home_path):
            if os.path.isfile(os.path.join(home_path, XML_ADDRESS)) and \
               os.path.isfile(os.path.join(home_path, CSV_ADDRESS)):
                homes.append(home_path)
    return homes

def create_dwelling(home_path, name, schedule_file, duration, **kwargs):
    return Dwelling(
        name=name,
        start_time=Start,
        time_res=dt.timedelta(minutes=t_res),
        duration=duration,
        hpxml_file=os.path.join(home_path, XML_ADDRESS),
        hpxml_schedule_file=schedule_file,
        weather_file=WEATHER_FILE if os.path.isfile(WEATHER_FILE) else DEFAULT_WEATHER,
        Equipment={"Clothes Dryer": {"equipment_class": ScheduledLoad}},
        **kwargs,
    )


def test_dryer_override(home_path):
    dw = create_dwelling(
        home_path,
        "DryerOverrideTest",
        os.path.join(home_path, CSV_ADDRESS),
        dt.timedelta(hours=1),
        verbosity=1,
        save_results=False,
    )
    dryer = dw.equipment.get("Clothes Dryer")
    if not isinstance(dryer, ScheduledLoad) or not dryer.is_electric:
        raise ValueError("Select a home with an electric clothes dryer and a dryer power schedule.")

    print(f"Testing {type(dryer).__name__} in {home_path}")
    for command_kw in (1.0, 0.0, 1.0):
        timestamp = dw.current_time
        dw.update(control_signal={"Clothes Dryer": {"P Setpoint": command_kw}})
        print(f"{timestamp} | commanded {command_kw:.3f} kW | measured {dryer.electric_kw:.3f} kW")
        if not math.isclose(dryer.electric_kw, command_kw, abs_tol=1e-6):
            raise RuntimeError("The dryer did not follow its power command.")
    print("PASS: The dryer followed all three power commands.")


def remove_first_day(df, start_date):
    if 'Time' not in df.columns:
        df = df.reset_index()
        if 'index' in df.columns:
            df.rename(columns={'index': 'Time'}, inplace=True)
    df['Time'] = pd.to_datetime(df['Time'], errors='coerce')
    first_day_end = start_date + pd.Timedelta(days=1)
    return df[df['Time'] >= first_day_end].copy()

def aggregate_results(homes, work_dir):
    all_ctrl, all_base = [], []
    for home in homes:
        results_dir = os.path.join(home, "Results")
        ctrl_file = os.path.join(results_dir, "dryer_controlled.csv")
        base_file = os.path.join(results_dir, "dryer_baseline.csv")
        
        if os.path.exists(ctrl_file):
            df_ctrl = pd.read_csv(ctrl_file)
            df_ctrl["Home"] = os.path.basename(home)
            all_ctrl.append(df_ctrl)

        if os.path.exists(base_file):
            df_base = pd.read_csv(base_file)
            df_base["Home"] = os.path.basename(home)
            all_base.append(df_base)

    if all_ctrl:
        df_ctrl_all = pd.concat(all_ctrl, ignore_index=True)
        df_ctrl_all.to_csv(os.path.join(work_dir, filename + "_controlled.csv"), index=False)

    if all_base:
        df_base_all = pd.concat(all_base, ignore_index=True)
        df_base_all.to_csv(os.path.join(work_dir, filename + "_baseline.csv"), index=False)
    print("Aggregated CSVs written!")

def advance_dwelling(home, phase, current_time, control_signal=None):
    try:
        return home["dw"].update(control_signal=control_signal)
    except Exception as exc:
        name = os.path.basename(home["path"])
        raise RuntimeError(f"{phase} failed for {name} at {current_time}: {exc}") from exc


def fleet_timesteps(sim_times, phase):
    """Report completed simulation minutes periodically, even in quiet stretches."""
    last_report = monotonic()
    for step_index, current_time in enumerate(sim_times):
        yield step_index, current_time
        now = monotonic()
        if now - last_report >= 10 or step_index + 1 == len(sim_times):
            print(
                f"{phase}: completed {step_index + 1}/{len(sim_times)} "
                f"timesteps through {current_time}",
                flush=True,
            )
            last_report = now


def run_fleet_feedback(fleet_data, sim_times):
    step_hours = t_res / 60
    previous_average_power_kw = None
    integral_error = 0.0
    previous_error = None
    num_homes = len(fleet_data)
    vpp_state_log = []

    for step_index, current_time in fleet_timesteps(sim_times, "Controlled"):
        feedback_kw = previous_average_power_kw
        is_vpp_active = VPP_START_TIME <= current_time.time() < VPP_END_TIME

        for h in fleet_data:
            h["queued_kwh"] += h["scheduled_kw"][step_index] * step_hours

        # 2. VPP / PID Logic
        if is_vpp_active and feedback_kw is not None:
            error = AVERAGE_SETPOINT_KW - feedback_kw
            integral_error += error

            # --- ANTI-WINDUP CLAMPING ---
            # Prevent the integral from building up a massive "memory" when error stays positive or negative for hours
            MAX_INTEGRAL = 0.1
            MIN_INTEGRAL = -0.5
            integral_error = max(min(integral_error, MAX_INTEGRAL), MIN_INTEGRAL)

            derivative_error = 0.0 if previous_error is None else error - previous_error
            previous_error = error

            pid_output = (KP * error) + (KI * integral_error) + (KD * derivative_error)

            if pid_output < -AVERAGE_DEADBAND_KW:
                total_kw_to_drop = abs(pid_output) * num_homes
                active_normal_homes = [h for h in fleet_data if h["mode"] == "NORMAL" and h["queued_kwh"] > 0]
                random.shuffle(active_normal_homes)

                units_to_shed = int(total_kw_to_drop / ESTIMATED_SHED_KW)
                shed_applied = min(units_to_shed, len(active_normal_homes))
                for h in active_normal_homes[:shed_applied]:
                    h["mode"] = "SHED"
                    h["pending_off"] = True

            elif pid_output > AVERAGE_DEADBAND_KW:
                total_kw_to_add = pid_output * num_homes
                shed_homes = [h for h in fleet_data if h["mode"] == "SHED" and h["queued_kwh"] > 0]
                random.shuffle(shed_homes)

                units_to_restore = int(total_kw_to_add / ESTIMATED_SHED_KW)
                restored_applied = min(units_to_restore, len(shed_homes))
                for h in shed_homes[:restored_applied]:
                    h["mode"] = "NORMAL"
                    h["pending_off"] = True
        else:
            for h in fleet_data:
                if h["mode"] == "SHED":
                    h["mode"] = "NORMAL"
                    h["pending_off"] = True
            integral_error = 0.0
            previous_error = None


        fleet_total_kw = 0.0
        commanded_dryer_kw = 0.0
        measured_dryer_kw = 0.0
        for h in fleet_data:
            dw = h["dw"]
            if dw.current_time != current_time:
                raise ValueError(f"Controlled dwelling is out of sync for {h['path']} at {current_time}.")

            if h["dryer"] is None:
                results = advance_dwelling(h, "Controlled", current_time)
            else:
                power_fraction = DUTY_CYCLE_FRACTION if h["mode"] == "SHED" else 1.0
                command_kw = min(h["max_kw"] * power_fraction, h["queued_kwh"] / step_hours)
                if h["pending_off"]:
                    command_kw = 0.0
                    h["pending_off"] = False

                results = advance_dwelling(
                    h, "Controlled", current_time,
                    control_signal={"Clothes Dryer": {"P Setpoint": command_kw}},
                )
                actual_dryer_kw = h["dryer"].electric_kw
                h["queued_kwh"] = max(0.0, h["queued_kwh"] - actual_dryer_kw * step_hours)
                commanded_dryer_kw += command_kw
                measured_dryer_kw += actual_dryer_kw

            fleet_total_kw += results["Total Electric Power (kW)"]

        previous_average_power_kw = fleet_total_kw / num_homes
        vpp_state_log.append({
            "Time": current_time,
            "Target Average Power (kW)": AVERAGE_SETPOINT_KW if is_vpp_active else "OFF",
            "Feedback Average Power (kW)": feedback_kw if is_vpp_active else None,
            "Actual Average Power (kW)": previous_average_power_kw,
            "Aggregate Power (kW)": fleet_total_kw,
            "Commanded Dryer Power (kW)": commanded_dryer_kw,
            "Measured Dryer Power (kW)": measured_dryer_kw,
            "Deferred Dryer Energy (kWh)": sum(h["queued_kwh"] for h in fleet_data),
            "Units in NORMAL": sum(h["mode"] == "NORMAL" for h in fleet_data),
            "Units in SHED": sum(h["mode"] == "SHED" for h in fleet_data),
        })

    return vpp_state_log


#########################################
# MAIN EXECUTION
#########################################

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run dryer load shaping or test the dryer override.")
    parser.add_argument(
        "--test-override",
        metavar="HOME_DIR",
        help="Run a three-step electric dryer test using the given home directory.",
    )
    args = parser.parse_args()
    if args.test_override:
        try:
            test_dryer_override(Path(args.test_override).resolve())
        except (ValueError, RuntimeError, OSError) as exc:
            parser.exit(1, f"Override test failed: {exc}\n")
        raise SystemExit(0)

    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(WEATHER_DIR, exist_ok=True)
    
    for item in os.listdir(DEFAULT_INPUT):
        src = os.path.join(DEFAULT_INPUT, item)
        dst = os.path.join(INPUT_DIR, item)
        if os.path.isdir(src) and not os.path.exists(dst):
            shutil.copytree(src, dst)
            
    if not os.path.exists(WEATHER_FILE):
        shutil.copy(DEFAULT_WEATHER, WEATHER_FILE)

    homes = find_all_homes(INPUT_DIR)
    if not homes:
        print("No homes found. Exiting.")
        exit()

    # =========================================================================
    # PASS 1: OCHRE BASELINE RUN
    # =========================================================================
    print(f"--- PASS 1: Running Baseline OCHRE for {len(homes)} homes ---")
    baseline_dwellings = []
    successful_homes = [] # Track which homes actually survived initialization
    
    def init_base(home_path):
        dw = create_dwelling(
            home_path,
            f"Base_{os.path.basename(home_path)}",
            os.path.join(home_path, CSV_ADDRESS),
            dt.timedelta(days=Duration),
            verbosity=7,
        )
        return {"path": home_path, "dw": dw}
        
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        # Use a dictionary to map the future back to the home path for logging
        futures = {executor.submit(init_base, h): h for h in homes}
        for f in concurrent.futures.as_completed(futures):
            home_path = futures[f]
            try:
                baseline_dwellings.append(f.result())
                successful_homes.append(home_path)
            except Exception as e:
                # Catch the error, print a warning, and move on
                print(f"Skipping {os.path.basename(home_path)} due to init error: {e}")
                
    # Use the same homes for baseline and controlled results.
    homes = successful_homes
            
    if not homes:
        raise SystemExit("No baseline dwellings initialized successfully.")

    sim_times = baseline_dwellings[0]["dw"].sim_times
    
    # Run Baseline Loop
    for _, current_time in fleet_timesteps(sim_times, "Baseline"):
        for b in baseline_dwellings:
            advance_dwelling(b, "Baseline", current_time)
            
    # Extract True Baseline Data
    baseline_data = {}
    for b in baseline_dwellings:
        df, _, _ = b["dw"].finalize()
        baseline_data[b["path"]] = df

    del baseline_dwellings, futures, b

    print("--- PASS 2: Running Controlled OCHRE with Fleet Feedback ---")

    def init_ctrl(home_path):
        dw = create_dwelling(
            home_path,
            f"Ctrl_{os.path.basename(home_path)}",
            os.path.join(home_path, CSV_ADDRESS),
            dt.timedelta(days=Duration),
            verbosity=7,
        )
        dryer = dw.equipment.get("Clothes Dryer")
        if dryer is not None and dryer.is_electric:
            baseline = baseline_data[home_path]
            if "Time" in baseline.columns:
                baseline = baseline.set_index("Time")
            scheduled_kw = baseline["Clothes Dryer Electric Power (kW)"].reindex(sim_times).to_numpy()
            if not np.isfinite(scheduled_kw).all() or (scheduled_kw < 0).any():
                raise ValueError(f"Invalid or missing baseline dryer power for {home_path}.")
        else:
            dryer = None
            scheduled_kw = np.zeros(len(sim_times))

        return {
            "path": home_path,
            "dw": dw,
            "dryer": dryer,
            "scheduled_kw": scheduled_kw,
            "max_kw": scheduled_kw.max(),  # Use the baseline peak as the dispatch limit.
            "queued_kwh": 0.0,
            "mode": "NORMAL",
            "pending_off": False,
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        fleet_data = list(executor.map(init_ctrl, homes))

    vpp_state_log = run_fleet_feedback(fleet_data, sim_times)

    print("Simulation complete! Finalizing results...")
    
    CTRL_COLS = ["Time", "Total Electric Power (kW)", "Total Electric Energy (kWh)", "Clothes Dryer Electric Power (kW)"]
    
    for c in fleet_data:
        home_path = c["path"]
        results_dir = os.path.join(home_path, "Results")
        os.makedirs(results_dir, exist_ok=True)
        
        # Save Control
        df_ctrl, _, _ = c["dw"].finalize()
        df_ctrl = remove_first_day(df_ctrl, Start)
        df_ctrl = df_ctrl[[col for col in CTRL_COLS if col in df_ctrl.columns]]
        df_ctrl.to_csv(os.path.join(results_dir, 'dryer_controlled.csv'), index=False)
        
        # Save Baseline (Calculated in Pass 1)
        df_base = baseline_data[home_path]
        df_base = remove_first_day(df_base, Start)
        df_base = df_base[[col for col in CTRL_COLS if col in df_base.columns]]
        df_base.to_csv(os.path.join(results_dir, 'dryer_baseline.csv'), index=False)

    # Aggregate CSVs
    aggregate_results(homes, WORKING_DIR)

    # Export the fleet log for the same period as the power results.
    df_vpp_log = remove_first_day(pd.DataFrame(vpp_state_log), Start)
    vpp_log_path = os.path.join(WORKING_DIR, filename + "_VPP_Fleet_States.csv")
    df_vpp_log.to_csv(vpp_log_path, index=False)
    print(f"VPP State Log saved to: {vpp_log_path}")