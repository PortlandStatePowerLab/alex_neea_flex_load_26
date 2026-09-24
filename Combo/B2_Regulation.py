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
import shutil
import datetime as dt
import pandas as pd
import re
from ochre.utils.schedule import ALL_SCHEDULE_NAMES
import concurrent.futures
from pathlib import Path
import numpy as np
import random

# Settings and reusable setup are owned by B_Common.
# These scripts retain their existing baseline + scheduled-control workflow.
try:
    from . import B_Common as common
except ImportError:
    import B_Common as common

CONFIG = common.load_configuration()
create_home_schedule = common.create_home_schedule
count = 0

def determine_control(sim_time, current_temp_c, home_schedule_td, home_charger_kw=None, 
                      wh_delay=None, hvac_delay=None, **kwargs):
    # Default offsets to 0 seconds if not provided
    wh_delay = wh_delay if wh_delay is not None else pd.Timedelta(seconds=0)
    hvac_delay = hvac_delay if hvac_delay is not None else pd.Timedelta(seconds=0)

    ctrl_signal = common.build_norm_cntrl(
        CONFIG, {"home_charger_kw": home_charger_kw}, sim_time
    )

    # Add HVAC if simulated, checking the month to separate Heating vs Cooling
    # Let's assume May (5) through Sept (9) is Cooling Season in Portland
    is_cooling_season = sim_time.month in [5, 6, 7, 8, 9]

    if CONFIG["HVAC_SIMULATION"] == "ON":
        if is_cooling_season:
            # Normal cooling control
            ctrl_signal['HVAC Cooling'] = {
                'Setpoint': CONFIG["AC_TbaselineC"],
                'Deadband': CONFIG["AC_TdeadbandC"],
                'Load Fraction': 1,
            }
            # Suppress heating by pushing setpoint extremely low
            ctrl_signal['HVAC Heating'] = {
                'Setpoint': CONFIG["HEAT_Tcontrol_GEC"],
                'Deadband': CONFIG["HEAT_TdeadbandC"],
                'Load Fraction': 1,
            }
        else:
            # Normal heating control
            ctrl_signal['HVAC Heating'] = {
                'Setpoint': CONFIG["HEAT_TbaselineC"],
                'Deadband': CONFIG["HEAT_TdeadbandC"],
                'Load Fraction': 1,
            }
            # Suppress cooling by pushing setpoint extremely high
            ctrl_signal['HVAC Cooling'] = {
                'Setpoint': CONFIG["AC_Tcontrol_GEC"],
                'Deadband': CONFIG["AC_TdeadbandC"],
                'Load Fraction': 1,
            }

    # Add dryers if simulated
    if CONFIG["DRYER_SIMULATION"] == "ON":
        ctrl_signal['Clothes Dryer'] = {
            'Load Fraction': 1  # 1 = Normal schedule operation
        }

    # Add batteries if simulated
    if CONFIG["BATTERY_SIMULATION"] == "ON":
        ctrl_signal['Battery'] = {
            'P Setpoint': CONFIG["P_Battery_IDLE_KW"]
        }


    midnight = pd.to_datetime(sim_time.date())

    # Define modes in priority order: 
    # (Mode Name, WH_SP, WH_DB, AC_SP, AC_DB, HEAT_SP, HEAT_DB)
    modes = [
        ('ALU', CONFIG["WH_Tcontrol_ALUC"], CONFIG["WH_Tcontrol_ALUdeadbandC"], CONFIG["AC_Tcontrol_ALUC"], CONFIG["AC_Tcontrol_ALUdeadbandC"], CONFIG["HEAT_Tcontrol_ALUC"], CONFIG["HEAT_Tcontrol_ALUdeadbandC"]),
        ('LU',  CONFIG["WH_Tcontrol_LOADC"], CONFIG["WH_Tcontrol_LOADdeadbandC"], CONFIG["AC_Tcontrol_LOADC"], CONFIG["AC_Tcontrol_LOADdeadbandC"], CONFIG["HEAT_Tcontrol_LOADC"], CONFIG["HEAT_Tcontrol_LOADdeadbandC"]),
        ('S',   CONFIG["WH_Tcontrol_SHEDC"], CONFIG["WH_Tcontrol_deadbandC"], CONFIG["AC_Tcontrol_SHEDC"], CONFIG["AC_Tcontrol_deadbandC"], CONFIG["HEAT_Tcontrol_SHEDC"], CONFIG["HEAT_Tcontrol_deadbandC"]),
        ('CP',  CONFIG["WH_Tcontrol_CPC"], CONFIG["WH_Tcontrol_CPdeadbandC"], CONFIG["AC_Tcontrol_CPC"], CONFIG["AC_Tcontrol_CPdeadbandC"], CONFIG["HEAT_Tcontrol_CPC"], CONFIG["HEAT_Tcontrol_CPdeadbandC"]),
        ('GE',  CONFIG["WH_Tcontrol_GEC"], CONFIG["WH_Tcontrol_GEdeadbandC"], CONFIG["AC_Tcontrol_GEC"], CONFIG["AC_Tcontrol_GEdeadbandC"], CONFIG["HEAT_Tcontrol_GEC"], CONFIG["HEAT_Tcontrol_GEdeadbandC"])
    ]

    # Helper function to evaluate active mode given a specific device delay
    def get_active_mode_for_delay(delay_td):
        for mode_data in modes:
            mode_name = mode_data[0]
            
            # Check Morning with delay offset
            m_start, m_end = home_schedule_td[f'M_{mode_name}']
            if (midnight + m_start + delay_td) <= sim_time < (midnight + m_end + delay_td):
                return mode_data

            # Check Evening with delay offset
            e_start, e_end = home_schedule_td[f'E_{mode_name}']
            if (midnight + e_start + delay_td) <= sim_time < (midnight + e_end + delay_td):
                return mode_data
        return None

    # Evaluate device-specific active modes
    wh_mode = get_active_mode_for_delay(wh_delay)
    hvac_mode = get_active_mode_for_delay(hvac_delay)
    base_mode = get_active_mode_for_delay(pd.Timedelta(seconds=0)) # For EV and Battery

    # Apply WH setpoints
    if CONFIG["WH_SIMULATION"] == "ON" and wh_mode:
        _, wh_sp, wh_db, _, _, _, _ = wh_mode
        ctrl_signal['Water Heating'].update({'Setpoint': wh_sp, 'Deadband': wh_db})

    # Apply HVAC setpoints
    if CONFIG["HVAC_SIMULATION"] == "ON" and hvac_mode:
        _, _, _, ac_sp, ac_db, heat_sp, heat_db = hvac_mode
        if is_cooling_season:
            ctrl_signal['HVAC Cooling'].update({'Setpoint': ac_sp, 'Deadband': ac_db})
        else:
            ctrl_signal['HVAC Heating'].update({'Setpoint': heat_sp, 'Deadband': heat_db})

    # Add EV logic based on unshifted/base schedule
    if CONFIG["EV_SIMULATION"] == "ON" and home_charger_kw is not None:
        ev_state = 'Normal'
        if base_mode:
            current_mode = base_mode[0]
            if current_mode == 'S':
                ev_state = 'Shed'
            elif current_mode == 'CP':
                ev_state = 'CP'
            elif current_mode == 'GE':
                ev_state = 'GE'

        # Prevent divide by zero error        
        fraction = CONFIG["EV_SHED_PCT"] if ev_state == 'Shed' else (CONFIG["EV_CP_PCT"] if ev_state == 'CP' else (CONFIG["EV_GE_PCT"] if ev_state == 'GE' else 1.0))
        commanded_kw = abs(fraction * home_charger_kw)
        ctrl_signal['EV'] = {'Max Power': max(commanded_kw, 0.001)}

    # Add battery logic base schedule
    if CONFIG["BATTERY_SIMULATION"] == "ON":
        battery_state = base_mode[0] if base_mode else 'Normal'
        battery_p_map = {
            'ALU': CONFIG["P_Battery_ALU_KW"],
            'LU': CONFIG["P_Battery_LU_KW"],
            'S': CONFIG["P_Battery_SHED_KW"],
            'CP': CONFIG["P_Battery_CP_KW"],
            'GE': CONFIG["P_Battery_GE_KW"]
        }
        battery_p = battery_p_map.get(battery_state, CONFIG["P_Battery_IDLE_KW"])
        ctrl_signal['Battery'] = {'P Setpoint': battery_p}

    return ctrl_signal

#########################################
# SCHEDULE FILTERING
#########################################

def filter_schedules(home_path):
    orig_sched_file = os.path.join(home_path, CONFIG["CSV_ADDRESS"])
    filtered_sched_file = os.path.join(home_path, 'filtered_schedules.csv')

    df_sched = pd.read_csv(orig_sched_file)
    
    # NEW FIX: Inject the EV charging schedule if missing
    if 'electric_vehicle_charging' not in df_sched.columns:
        # A value of 1 means the EV is plugged in and available. 
        # A value of 0 means the EV is disconnected (driving).
        # This defaults to always plugged in. You can replace 1.0 with a custom profile if needed.
        df_sched['electric_vehicle_charging'] = 1.0

    valid_schedule_names = set(ALL_SCHEDULE_NAMES.keys())
    
    # Catch any variation of EV / Vehicle schedules
    filtered_columns = [
        col for col in df_sched.columns 
        if col in valid_schedule_names 
        or 'ev' in col.lower() 
        or 'vehicle' in col.lower()
        or 'plug' in col.lower()
    ]
    
    dropped_columns = [col for col in df_sched.columns if col not in filtered_columns]
    if dropped_columns:
        print(f"Dropped invalid schedules for {home_path}: {dropped_columns}")

    df_sched_filtered = df_sched[filtered_columns]
    df_sched_filtered.to_csv(filtered_sched_file, index=False)
    return filtered_sched_file

def prepare_schedules(home_path, sched_cfg, t_res_minutes=15):
    """
    Creates a baseline schedule and a controlled schedule.
    Uses a load accumulator to stretch run times during shed periods,
    conserving the total run time (area under the curve).
    """
    orig_sched_file = os.path.join(home_path, CONFIG["CSV_ADDRESS"])
    base_sched_file = os.path.join(home_path, 'baseline_schedules.csv')
    ctrl_sched_file = os.path.join(home_path, 'controlled_schedules.csv')

    df_sched = pd.read_csv(orig_sched_file)

    # if OCHRE valid names filter strips everything, keep original columns + EV variants
    valid_schedule_names = set(ALL_SCHEDULE_NAMES.keys())
    filtered_columns = [
        col for col in df_sched.columns 
        if col in valid_schedule_names 
        or 'ev' in col.lower() 
        or 'vehicle' in col.lower()
        or 'plug' in col.lower()
    ]
    
    if not filtered_columns:
        print(f"[WARNING] No columns matched ALL_SCHEDULE_NAMES for {home_path}. Retaining all original columns.")
        df_sched = df_sched.copy()
    else:
        df_sched = df_sched[filtered_columns].copy()

    # Save baseline schedule
    df_sched.to_csv(base_sched_file, index=False)

    # Find the dryer column
    dryer_cols = [c for c in df_sched.columns if 'dryer' in c.lower()]
    if not dryer_cols:
        df_sched.to_csv(ctrl_sched_file, index=False) # No dryer to shift
        return base_sched_file, ctrl_sched_file
    
    dryer_col = dryer_cols[0]

    # Create dummy datetime index for time-of-day masking
    df_sched['Datetime'] = pd.date_range(start="2018-01-01 00:00:00", periods=len(df_sched), freq=f'{t_res_minutes}min')
    df_sched.set_index('Datetime', inplace=True)
    
    # Track the active duty cycle for each timestep (default to 1.0 - no curtailment)
    duty_cycles = np.ones(len(df_sched), dtype=float)
    
    # Get the time of day as a timedelta from midnight for easy comparison
    time_of_day = df_sched.index - df_sched.index.normalize()
    
    # Map modes to their respective duty cycle variables defined in your script
    curtailment_modes = {
        'S': CONFIG["dryer_duty_cycle_shed"],
        'CP': CONFIG["dryer_duty_cycle_cp"],
        'GE': CONFIG["dryer_duty_cycle_ge"]
    }

    # Build the duty cycle array based on all shed periods in the schedule config
    for tod in ['M', 'E']:
        for mode, dc_value in curtailment_modes.items():
            key = f"{tod}_{mode}"
            if key in sched_cfg:
                start_td, end_td = sched_cfg[key]
                # Apply the duty cycle where the time of day falls within the start and end
                mask = (time_of_day >= start_td) & (time_of_day < end_td)
                # If modes overlap, apply the most aggressive curtailment (lowest duty cycle)
                duty_cycles[mask] = np.minimum(duty_cycles[mask], dc_value)

    # Create boolean mask for boundary detection (where duty cycle < 1)
    in_shed = duty_cycles < 1.0

    # Accumulate and distribute load to conserve total schedule sum
    orig_vals = df_sched[dryer_col].values
    new_vals = np.zeros_like(orig_vals, dtype=float)
    
    # Find the maximum normal operating coefficient (usually 1.0)
    max_cap = orig_vals.max() if orig_vals.max() > 0 else 1.0
    work_queue = 0.0
    
    for i in range(len(orig_vals)):
        # Add the current timestep's scheduled work to the queue
        work_queue += orig_vals[i]
        
        # Clean up floating point precision remnants
        if work_queue < 1e-6:
            work_queue = 0.0
            
        if work_queue > 0:
            # Detect any boundary (entering or exiting a shed)
            # Force a 0 for exactly one timestep to split the event
            if i > 0 and in_shed[i] != in_shed[i-1]:
                run_amt = 0.0
            else:
                # Throttle using the specific duty cycle for this timestep
                allowed_rate = max_cap * duty_cycles[i]
                run_amt = min(work_queue, allowed_rate)
                
            new_vals[i] = run_amt
            work_queue -= run_amt

    # Assign new values back to the dataframe
    df_sched[dryer_col] = new_vals
    df_sched.reset_index(drop=True, inplace=True)
    
    # Save controlled schedule
    df_sched.to_csv(ctrl_sched_file, index=False)
    
    return base_sched_file, ctrl_sched_file

#########################################
# SIMULATION FUNCTION
#########################################

def simulate_home(home_path, weather_file_path, schedule_cfg):
    # 1. Use prepare_schedules instead of filter_schedules to get the separated files
    base_sched_file, ctrl_sched_file = prepare_schedules(home_path, schedule_cfg, CONFIG["t_res"])
    
    config = dict(CONFIG)
    config["WEATHER_FILE"] = weather_file_path
    results_dir = os.path.join(home_path, "Results")
    os.makedirs(results_dir, exist_ok=True)
    base_dwelling, home_info = common.init_home(
        home_path, config, base_sched_file, run_kind="baseline"
    )
    home_charger_kw = home_info["home_charger_kw"]

    for t_base in base_dwelling.sim_times:
        base_ctrl = common.build_norm_cntrl(config, home_info, t_base)
        base_dwelling.update(control_signal=base_ctrl)
    df_base, _, _ = base_dwelling.finalize()

    # Generate random response time delays for WH and HVAC for this home
    wh_delay_sec = random.uniform(CONFIG["WH_RESPONSE_MIN"], CONFIG["WH_RESPONSE_MAX"])
    hvac_delay_sec = random.uniform(CONFIG["HVAC_RESPONSE_MIN"], CONFIG["HVAC_RESPONSE_MAX"])
    
    wh_delay = pd.Timedelta(seconds=wh_delay_sec)
    hvac_delay = pd.Timedelta(seconds=hvac_delay_sec)

    # Create a separate controlled dwelling using the same shared setup.
    sim_dwelling, _ = common.init_home(
        home_path, config, ctrl_sched_file, run_kind="controlled"
    )

    # Get HPWH unit only if WH_SIMULATION is ON
    hpwh_unit = None
    if CONFIG["WH_SIMULATION"] == "ON":
        hpwh_unit = sim_dwelling.get_equipment_by_end_use('Water Heating')
        
    for sim_time in sim_dwelling.sim_times:
        # Provide a default temp if WH is off so determine_control still works
        current_setpt = CONFIG["WH_TinitC"] 
        if hpwh_unit is not None:
            current_setpt = hpwh_unit.schedule.loc[sim_time, 'Water Heating Setpoint (C)']
            
        control_cmd = determine_control(
            sim_time=sim_time, 
            current_temp_c=current_setpt, 
            home_schedule_td=schedule_cfg, 
            home_charger_kw=home_charger_kw,
            wh_delay=wh_delay,
            hvac_delay=hvac_delay
        )
        
        if control_cmd:
            sim_dwelling.update(control_signal=control_cmd)
        else:
            sim_dwelling.update()
            
    df_ctrl, _, _ = sim_dwelling.finalize()

    # --- Formatting Output ---
    df_ctrl = common.format_results(df_ctrl, config)

    df_ctrl.to_csv(os.path.join(results_dir, 'home_controlled.csv'), index=False)

    return df_ctrl

#########################################
# FIND ALL HOMES
#########################################

def find_all_homes(base_dir):
    homes = []
    for item in os.listdir(base_dir):
        home_path = os.path.join(base_dir, item)
        if os.path.isdir(home_path):
            # Only add folders with required files
            if os.path.isfile(os.path.join(home_path, CONFIG["XML_ADDRESS"])) and \
               os.path.isfile(os.path.join(home_path, CONFIG["CSV_ADDRESS"])):
                homes.append(home_path)
    print(f"-++++++++++++ {homes}\n {base_dir}",)
    return homes


#########################################
# MAIN EXECUTION
#########################################

failcount = 0

if __name__ == "__main__":
    # Ensure working folders exist
    os.makedirs(CONFIG["INPUT_DIR"], exist_ok=True)
    os.makedirs(CONFIG["WEATHER_DIR"], exist_ok=True)
    try:
        weather_path = Path(CONFIG["WEATHER_DIR"])
        weather_path.mkdir(parents=True, exist_ok=True)
        print(f"[INFO] Weather directory ready: {weather_path}")
    except Exception as e:
        print(f"[ERROR] Failed to create directory {weather_path}: {e}")
    count2 = 0

    # Copy all homes from defaults (if not already copied)
    for item in os.listdir(CONFIG["DEFAULT_INPUT"]):
        count2 +=1
        if count2 == 20:
            print(f"-----------", CONFIG["DEFAULT_INPUT"], item, CONFIG["INPUT_DIR"])
        src = os.path.join(CONFIG["DEFAULT_INPUT"], item)
        dst = os.path.join(CONFIG["INPUT_DIR"], item)
        if os.path.isdir(src) and not os.path.exists(dst):
            shutil.copytree(src, dst)
            count +=1
        count +=1
    # Copy weather file
    if not os.path.exists(CONFIG["WEATHER_FILE"]):
        shutil.copy(CONFIG["DEFAULT_WEATHER"], CONFIG["WEATHER_FILE"])
        count +=1

    # Discover homes
    homes = find_all_homes(CONFIG["INPUT_DIR"])
    print(f"homes: ", CONFIG["INPUT_DIR"])
    print(f"Found {len(homes)} homes")

    # Parallel simulations
    # $ grep -rn "read_psm3(" .
    # ./ochre/utils/schedule.py:186:        df, location = pvlib.iotools.read_psm3(weather_file, map_variables=True)
    # Change to read_nsrdb_psm4 
    with concurrent.futures.ProcessPoolExecutor(max_workers=8) as executor:
        futures = []
        for home in homes:
            # Extract digits from the home folder name to use as a unique ID
            home_basename = os.path.basename(home)
            # home_num = sum(int(c) for c in home_basename if c.isdigit())
            home_num_str = re.sub(r'\D', '', home_basename)
            home_num = int(home_num_str) if home_num_str else 0
            
            # Generate the exact shifted timedeltas for THIS specific home
            home_sched_td = create_home_schedule(CONFIG["my_schedule1"], bins=CONFIG["bins"], home_idx=home_num)
            
            # Submit to the thread pool
            futures.append(executor.submit(simulate_home, home, CONFIG["WEATHER_FILE"], home_sched_td))

        for f in concurrent.futures.as_completed(futures):
            try:
                f.result()  # forces execution and raises exceptions if any
            except Exception as e:
                failcount += 1
                print("Simulation failed:", e, failcount)

    print("All simulations complete!")


def aggregate_results(homes, work_dir):
    all_ctrl, all_base = [], []

    for home in homes:
        results_dir = os.path.join(home, "Results")
        ctrl_file = os.path.join(results_dir, "home_controlled.csv")
        base_file = os.path.join(results_dir, "home_baseline.csv")
        #print(f"Aggregated CSVs written to {results_dir}!")
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
        df_ctrl_all.to_csv(os.path.join(work_dir, CONFIG["filename"] + "_controlled.csv"), index=False)

    if all_base:
        df_base_all = pd.concat(all_base, ignore_index=True)
        df_base_all.to_csv(os.path.join(work_dir, CONFIG["filename"] + "_baseline.csv"), index=False)
    
    print(f"Aggregated CSVs written! {count}")

if __name__ == "__main__":
    aggregate_results(homes, CONFIG["WORKING_DIR"])