# -*- coding: utf-8 -*-
"""
Created on Wed Sep  3 17:39:26 2025
Modified on Nov 19 2025
Modified on Jul 27 2026

@author: danap
@edited by: jdinsmor
@edited for dryers by: t-metzler
"""

import os
import shutil
import datetime as dt
import pandas as pd
from ochre import Dwelling
from ochre.utils.schedule import ALL_SCHEDULE_NAMES
import concurrent.futures
from pathlib import Path
import ochre
import numpy as np

#########################################
# USER SETTINGS
#########################################

#Gallons, MLU, MLU duration, Shed duration, ELU, ELU duration, Shed duration, Offset sheds 
filename = 'Dryer_Test_15'

#"HPWH 50 Input Files", "HPWH 66 Input Files/bldg", "HPWH 80 Input Files", "HPWH All Input Files/bldg"
Input_folder = "Dryer Input Files 2"

# Original OCHRE defaults folder
ochre_dir = Path(ochre.__file__).resolve().parent
DEFAULT_INPUT = ochre_dir / "defaults" / "Input Files"
print("OCHRE installed at:", ochre_dir)
print(DEFAULT_INPUT)

DEFAULT_WEATHER = ochre_dir / "defaults" / "Weather" / "USA_OR_Portland.Intl.AP.726980_TMY3.epw"
#DEFAULT_WEATHER = ochre_dir / "defaults" / "Weather" / "G4100510_2018.csv" 
# ^ Incorrect format for the weather file, it doesn't want csv
# G4100510 is Multnomah county weather station, code will complain this is missing but it doesn't work otherwise

# Safe working folder (writable)
script_dir = os.path.dirname(os.path.abspath(__file__))
fl_dir = os.path.dirname(script_dir)
WORKING_DIR = os.path.dirname(fl_dir)
INPUT_DIR = os.path.join(WORKING_DIR, Input_folder, "bldg")
WEATHER_DIR = os.path.join(WORKING_DIR, "Weather")
WEATHER_FILE = os.path.join(WEATHER_DIR, "USA_OR_Portland.Intl.AP.726980_TMY3.epw")
XML_ADDRESS = "home.xml"
CSV_ADDRESS = "in.schedules.csv"

#Duty cycle for shed
duty_cycle = 0.5


# Simulation parameters
Start = dt.datetime(2018, 1, 11, 0, 0)
Duration = 2  # days
t_res = 15  # minutes
                  
count = 0

# Schedule variant
my_schedule1 = {
    'M_LU_time': '07:00',
    'M_LU_duration': 0,
    'M_S_time': '08:30',
    'M_S_duration': 6,
    'E_ALU_time': '15:00',
    'E_ALU_duration': 0,
    'E_S_time': '17:00',
    'E_S_duration': 5
}

def shift_time(time_str, minutes):
    """Helper function to add minutes to an 'HH:MM' string."""
    # Using 'dt' to match your 'import datetime as dt' alias perfectly
    delta_t = dt.datetime.strptime(time_str, '%H:%M')
    new_delta_t = delta_t + dt.timedelta(minutes=minutes)
    return new_delta_t.strftime('%H:%M')

# List to hold all generated schedules
my_schedule = []

#minutes you will offset schedules
timestep = 15

#number of bins
bins = 1

# Generate schedules with offsets
for i in range(bins):
    offset = i * timestep  # Calculates offset
    new_sched = my_schedule1.copy()
    
    for key, value in new_sched.items():
        # Check if the key is a time variable
        if key.endswith('_time'):
            # Shift the start time
            new_sched[key] = shift_time(value, offset)
            
        # Note: durations remain exactly the same across all schedules
            
    my_schedule.append(new_sched)

#########################################
# TEMPERATURE CONVERSIONS F to C
#########################################

# def f_to_c(temp_f): 
#     return (temp_f - 32) * 5/9

# def f_to_c_DB(temp_f):
#     return 5/9 * temp_f

# Tcontrol_SHEDC = f_to_c(Tcontrol_SHEDF)
# Tcontrol_deadbandC = f_to_c_DB(Tcontrol_deadbandF)
# Tcontrol_LOADC = f_to_c(Tcontrol_LOADF)
# Tcontrol_LOADdeadbandC = f_to_c_DB(Tcontrol_LOADdeadbandF)
# TbaselineC = f_to_c(TbaselineF)
# TdeadbandC = f_to_c_DB(TdeadbandF)
# TinitC = f_to_c(Tinit)

#########################################
# AC CONTROL FUNCTION
#########################################

def determine_hvac_control(sim_time, sched_cfg, **kwargs):
    ctrl_signal = {
       'Clothes Dryer': {
            'Load Fraction': 1  # 1 = Normal schedule operation
        }
    }

    base_date = sim_time.date()
    def get_time_range(key_prefix):
        start = pd.to_datetime(f"{base_date} {sched_cfg[f'{key_prefix}_time']}")
        end = start + pd.Timedelta(hours=sched_cfg[f'{key_prefix}_duration'])
        return start, end

    ranges = {
        'M_LU': get_time_range('M_LU'),
        'M_S': get_time_range('M_S'),
        'E_ALU': get_time_range('E_ALU'),
        'E_S': get_time_range('E_S'),
    }

    if ranges['M_LU'][0] <= sim_time < ranges['M_LU'][1] or ranges['E_ALU'][0] <= sim_time < ranges['E_ALU'][1]:
        ctrl_signal['Clothes Dryer'].update({
            'Load Fraction': 1
        })
    elif ranges['M_S'][0] <= sim_time < ranges['M_S'][1] or ranges['E_S'][0] <= sim_time < ranges['E_S'][1]:
        ctrl_signal['Clothes Dryer'].update({
            'Load Fraction': 1
        })

    return ctrl_signal

#########################################
# SCHEDULE FILTERING
#########################################

def prepare_schedules(home_path, sched_cfg, t_res_minutes=15):
    """
    Creates a baseline schedule and a controlled schedule.
    Uses a load accumulator to stretch run times during shed periods,
    conserving the total run time (area under the curve).
    """
    orig_sched_file = os.path.join(home_path, CSV_ADDRESS)
    base_sched_file = os.path.join(home_path, 'baseline_schedules.csv')
    ctrl_sched_file = os.path.join(home_path, 'controlled_schedules.csv')

    df_sched = pd.read_csv(orig_sched_file)
    
    # Filter valid columns
    valid_schedule_names = set(ALL_SCHEDULE_NAMES.keys())
    filtered_columns = [col for col in df_sched.columns if col in valid_schedule_names]
    df_sched = df_sched[filtered_columns].copy()
    
    # Save baseline
    df_sched.to_csv(base_sched_file, index=False)

    # Find the dryer column
    dryer_cols = [c for c in df_sched.columns if 'dryer' in c.lower()]
    if not dryer_cols:
        df_sched.to_csv(ctrl_sched_file, index=False) # No dryer to shift
        return base_sched_file, ctrl_sched_file
    
    dryer_col = dryer_cols[0]

    # Create dummy datetime index for easy time-of-day masking
    df_sched['Datetime'] = pd.date_range(start="2018-01-01 00:00:00", periods=len(df_sched), freq=f'{t_res_minutes}min')
    df_sched.set_index('Datetime', inplace=True)
    
    # 1. Build a boolean mask for ALL shed periods
    in_shed = np.zeros(len(df_sched), dtype=bool)
    time_series = df_sched.index.time
    
    for prefix in ['M_S', 'E_S']:
        start_str = sched_cfg[f'{prefix}_time']
        duration_hrs = sched_cfg[f'{prefix}_duration']
        if duration_hrs <= 0: continue
        
        start_time = pd.to_datetime(start_str).time()
        end_time = (pd.to_datetime(start_str) + pd.Timedelta(hours=duration_hrs)).time()
        
        # Handle midnight crossovers safely
        if start_time < end_time:
            mask = (time_series >= start_time) & (time_series < end_time)
        else: 
            mask = (time_series >= start_time) | (time_series < end_time)
            
        in_shed = in_shed | mask

    # 2. Accumulate and distribute load to conserve total schedule sum
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
            # TRICK OCHRE: Detect any boundary (entering or exiting a shed)
            # Force a 0 for exactly one timestep to split the event
            if i > 0 and in_shed[i] != in_shed[i-1]:
                run_amt = 0.0
            else:
                # Throttle the max allowable rate if we are in a shed period
                if in_shed[i]:
                    allowed_rate = max_cap * duty_cycle
                else:
                    allowed_rate = max_cap
                    
                # Run the dryer up to the allowed rate, but no more than what's left in the queue
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
    # Get separate schedule files
    base_sched_file, ctrl_sched_file = prepare_schedules(home_path, schedule_cfg, t_res)
    
    results_dir = os.path.join(home_path, "Results")
    os.makedirs(results_dir, exist_ok=True)

    dwelling_args_local = {
        "start_time": Start,
        "time_res": dt.timedelta(minutes=t_res),
        "duration": dt.timedelta(days=Duration),
        "hpxml_file": os.path.join(home_path, XML_ADDRESS),
        # "initialization_time": dt.timedelta(days=1),
        "weather_file": weather_file_path,
        "verbosity": 7
        }


    # Run Baseline (Uses un-shifted schedule)
    base_dwelling = Dwelling(
        name="Dryer Baseline", 
        hpxml_schedule_file=base_sched_file, 
        **dwelling_args_local
    )
    base_dwelling.simulate()  # <--- ADD THIS LINE
    df_base, _, _ = base_dwelling.finalize()

    # print(df_base)
    # quit()

    # Run Controlled (Uses shifted schedule)
    sim_dwelling = Dwelling(
        name="Dryer Controlled", 
        hpxml_schedule_file=ctrl_sched_file, 
        **dwelling_args_local
    )
    sim_dwelling.simulate()
    df_ctrl, _, _ = sim_dwelling.finalize()

    # Formatting and saving results
    df_ctrl = remove_first_day(df_ctrl, Start)
    df_base = remove_first_day(df_base, Start)

    CTRL_COLS = [
        "Time", 
        "Total Electric Power (kW)",
        "Total Electric Energy (kWh)",
        "Clothes Dryer Electric Power (kW)" 
    ]
    
    df_ctrl = df_ctrl[[c for c in CTRL_COLS if c in df_ctrl.columns]]
    df_base = df_base[[c for c in CTRL_COLS if c in df_base.columns]]

    # for col in df_ctrl.columns:
    #     print("\n\n")
    #     print("="*70)
    #     print(col)
    #     print("="*70)
    # quit()
    
    df_ctrl.to_csv(os.path.join(results_dir, 'hpwh_controlled.csv'), index=False)
    df_base.to_csv(os.path.join(results_dir, 'hpwh_baseline.csv'), index=False)

    print("="*70)
    print(len(df_ctrl.notna ()))
    print(len(df_ctrl))
    print("="*70)
    return df_ctrl, df_base

#########################################
# FIND ALL HOMES
#########################################

def find_all_homes(base_dir):
    homes = []
    for item in os.listdir(base_dir):
        home_path = os.path.join(base_dir, item)
        if os.path.isdir(home_path):
            # Only add folders with required files
            if os.path.isfile(os.path.join(home_path, XML_ADDRESS)) and \
               os.path.isfile(os.path.join(home_path, CSV_ADDRESS)):
                homes.append(home_path)
    print(f"-++++++++++++ {homes}\n {base_dir}",)
    # print(len(homes))
    # x = list(set(homes))
    # print(len(x))
    # quit()
    return homes

#########################################
# DELETE FIRST DAY ONLY
#########################################

def remove_first_day(df, start_date):
    """
    Remove the first day of simulation results.
    Works whether 'Time' is a column or the index.
    """
    # If 'Time' column doesn't exist, try using the index
    if 'Time' not in df.columns:
        df = df.reset_index()
        if 'index' in df.columns:
            df.rename(columns={'index': 'Time'}, inplace=True)

    # Ensure Time is datetime
    df['Time'] = pd.to_datetime(df['Time'], errors='coerce')

    # Remove first day
    first_day_end = start_date + pd.Timedelta(days=1)
    return df[df['Time'] >= first_day_end].copy()



#########################################
# MAIN EXECUTION
#########################################

if __name__ == "__main__":
    # Ensure working folders exist
    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(WEATHER_DIR, exist_ok=True)
    try:
        weather_path = Path(WEATHER_DIR)
        weather_path.mkdir(parents=True, exist_ok=True)
        print(f"[INFO] Weather directory ready: {weather_path}")
    except Exception as e:
        print(f"[ERROR] Failed to create directory {weather_path}: {e}")
    count2 = 0

    # Copy all homes from defaults (if not already copied)
    for item in os.listdir(DEFAULT_INPUT):
        count2 +=1
        if count2 == 20:
            print(f"-----------", DEFAULT_INPUT, item, INPUT_DIR)
        src = os.path.join(DEFAULT_INPUT, item)
        dst = os.path.join(INPUT_DIR, item)
        if os.path.isdir(src) and not os.path.exists(dst):
            shutil.copytree(src, dst)
            count +=1
        count +=1
    # Copy weather file
    if not os.path.exists(WEATHER_FILE):
        shutil.copy(DEFAULT_WEATHER, WEATHER_FILE)
        count +=1

    # Discover homes
    homes = find_all_homes(INPUT_DIR)
    print(f"homes: ", INPUT_DIR)
    print(f"Found {len(homes)} homes")

    # Parallel simulations (threads are Windows-safe)
    # my_schedule is crazy but I wanted to vary schedules within the for loop, so I summed the digits in the home name and mod by # of bins to select one of the schedules
    # $ grep -rn "read_psm3(" .
    # ./ochre/utils/schedule.py:186:        df, location = pvlib.iotools.read_psm3(weather_file, map_variables=True)
    # Change to read_nsrdb_psm4 
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(simulate_home, home, WEATHER_FILE, my_schedule[sum(int(char) for char in home if char.isdigit()) % bins]) for home in homes]
        for f in concurrent.futures.as_completed(futures):
            try:
                f.result()  # forces execution and raises exceptions if any
            except Exception as e:
                print("\n\nSimulation failed:", e)

    print("All simulations complete!")




# def aggregate_results(homes, work_dir, ctrl_cols=None, base_cols=None):
#     all_ctrl, all_base = [], []

#     for home in homes:
#         results_dir = os.path.join(home, "Results")
#         ctrl_file = os.path.join(results_dir, "hpwh_controlled.csv")
#         base_file = os.path.join(results_dir, "hpwh_baseline.csv")

#         if os.path.exists(ctrl_file):
#             df_ctrl = pd.read_csv(ctrl_file)
#             if ctrl_cols:  # filter only selected columns
#                 df_ctrl = df_ctrl[[c for c in ctrl_cols if c in df_ctrl.columns]]
#             df_ctrl["Home"] = os.path.basename(home)
#             all_ctrl.append(df_ctrl)

#         if os.path.exists(base_file):
#             df_base = pd.read_csv(base_file)
#             if base_cols:
#                 df_base = df_base[[c for c in base_cols if c in df_base.columns]]
#             df_base["Home"] = os.path.basename(home)
#             all_base.append(df_base)

#     if all_ctrl:
#         df_ctrl_all = pd.concat(all_ctrl, ignore_index=True)
#         df_ctrl_all.to_csv(os.path.join(work_dir, "hpwh_controlled_all.csv"), index=False)

#     if all_base:
#         df_base_all = pd.concat(all_base, ignore_index=True)
#         df_base_all.to_csv(os.path.join(work_dir, "hpwh_baseline_all.csv"), index=False)

#     print("Aggregated CSVs written!")

def aggregate_results(homes, work_dir):
    all_ctrl, all_base = [], []

    for home in homes:
        results_dir = os.path.join(home, "Results")
        ctrl_file = os.path.join(results_dir, "hpwh_controlled.csv")
        base_file = os.path.join(results_dir, "hpwh_baseline.csv")
        print(f"Aggregated CSVs written to {results_dir}!")
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
        print(df_ctrl_all)

    if all_base:
        df_base_all = pd.concat(all_base, ignore_index=True)
        df_base_all.to_csv(os.path.join(work_dir, filename + "_baseline.csv"), index=False)
        print(df_base_all)
    
    print(f"Aggregated CSVs written! {count}")


if __name__ == "__main__":
    aggregate_results(homes, WORKING_DIR)

