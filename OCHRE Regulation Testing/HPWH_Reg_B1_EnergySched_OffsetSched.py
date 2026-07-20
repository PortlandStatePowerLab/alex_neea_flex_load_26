# -*- coding: utf-8 -*-
"""
Created on Wed Sep  3 17:39:26 2025
Modified on Nov 19 2025
Modified on Jun 17 2026
Modified on Jul 17 2026

@author: danap
@edited by: jdinsmor
@edited by: t-metzler
@edited by: alexwardwell5
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
filename = '2025_All_630_1_45_1700_1_45_OS'

#"HPWH 50 Input Files", "HPWH 66 Input Files/bldg", "HPWH 80 Input Files", "HPWH All Input Files/bldg"
Input_folder = "HPWH All Input Files"

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

REG_DIR = os.path.join(WORKING_DIR, "RegA Signal")
REG_ADDRESS = "RegA_Generated.csv"

# Simulation parameters
Start = dt.datetime(2018, 1, 11, 0, 0)
Duration = 2  # days
t_res =  1 # minutes

# HPWH control parameters (°F)
Tcontrol_SHEDF = 126
Tcontrol_deadbandF = 10
Tcontrol_LOADF = 130
Tcontrol_LOADdeadbandF = 2
TbaselineF = 130
TdeadbandF = 7
Tinit = 128
count = 0

# # Schedule variant
# my_schedule1 = {
#     'M_LU_time': '06:30',
#     'M_LU_duration': 1,
#     'M_S_time': '07:30',
#     'M_S_duration': 4.5,
#     'E_ALU_time': '17:00',
#     'E_ALU_duration': 1,
#     'E_S_time': '18:00',
#     'E_S_duration': 4.5
# }

# #new schedule variant with 0.25 hour shift for M_S and E_S, reduce secondary peak
# my_schedule2 = my_schedule1.copy()
# my_schedule2['M_S_duration'] = my_schedule1['M_S_duration'] + 0.25
# my_schedule2['E_S_duration'] = my_schedule1['E_S_duration'] + 0.25

# my_schedule3 = my_schedule1.copy()
# my_schedule3['M_S_duration'] = my_schedule1['M_S_duration'] + 0.5
# my_schedule3['E_S_duration'] = my_schedule1['E_S_duration'] + 0.5

# my_schedule4 = my_schedule1.copy()
# my_schedule4['M_S_duration'] = my_schedule1['M_S_duration'] + 0.75
# my_schedule4['E_S_duration'] = my_schedule1['E_S_duration'] + 0.75

# my_schedule = [my_schedule1, my_schedule2, my_schedule3, my_schedule4]

# Schedule variant
my_schedule1 = {
    'M_LU_time': '06:30',
    'M_LU_duration': 0,
    'M_S_time': '07:30',
    'M_S_duration': 0,
    'E_ALU_time': '13:00',
    'E_ALU_duration': 1,
    'E_S_time': '14:00',
    'E_S_duration': 6
}

reg_signal = pd.read_csv(
    os.path.join(REG_DIR, REG_ADDRESS)
)

def shift_time(time_str, minutes):
    """Helper function to add minutes to an 'HH:MM' string."""
    # Using 'dt' to match your 'import datetime as dt' alias perfectly
    delta_t = dt.datetime.strptime(time_str, '%H:%M')
    new_delta_t = delta_t + dt.timedelta(minutes=minutes)
    return new_delta_t.strftime('%H:%M')

# List to hold all generated schedules
my_schedule = []

#minutes you will offset schedules
timestep = 30

# Generate 4 schedules with offsets
for i in range(4):
    offset = i * timestep  # Calculates offset
    new_sched = my_schedule1.copy()
    
    for key, value in new_sched.items():
        # Check if the key is a time variable
        if key.endswith('_time'):
            # Shift the start time
            new_sched[key] = shift_time(value, offset)
            
        # Note: durations remain exactly the same across all schedules
            
    my_schedule.append(new_sched)

# Unpack for legacy references if needed elsewhere
my_schedule1 = my_schedule[0]
my_schedule2 = my_schedule[1]
my_schedule3 = my_schedule[2]
my_schedule4 = my_schedule[3]

#########################################
# TEMPERATURE CONVERSIONS F to C
#########################################

def f_to_c(temp_f): 
    return (temp_f - 32) * 5/9

def f_to_c_DB(temp_f):
    return 5/9 * temp_f

Tcontrol_SHEDC = f_to_c(Tcontrol_SHEDF)
Tcontrol_deadbandC = f_to_c_DB(Tcontrol_deadbandF)
Tcontrol_LOADC = f_to_c(Tcontrol_LOADF)
Tcontrol_LOADdeadbandC = f_to_c_DB(Tcontrol_LOADdeadbandF)
TbaselineC = f_to_c(TbaselineF)
TdeadbandC = f_to_c_DB(TdeadbandF)
TinitC = f_to_c(Tinit)

#########################################
# HPWH CONTROL FUNCTION
#########################################

def determine_hpwh_control(sim_time, current_temp_c, rega_sig, **kwargs):
    ctrl_signal = {
        'Water Heating': {
            'Setpoint': TbaselineC,
            'Deadband': TdeadbandC,
            'Load Fraction': 1,
        }
    }

    rega_cmd = rega_sig.loc[sim_time]

    rega_sp = TbaselineC + rega_cmd * 4

    ctrl_signal["Water Heating"].update({
        'Setpoint': rega_sp
    })

    return ctrl_signal

#########################################
# SCHEDULE FILTERING
#########################################

def signal_aggregator_mean():
    # assume sig_step in seconds and t_res in minutes
    reg_signal["timestamp"] = pd.to_datetime(reg_signal["Timestamp"])

    sig_step_dt = reg_signal["timestamp"].diff()
    sig_step = int(
        sig_step_dt.dt.total_seconds().mean()
    )
    ochre_step = t_res * 60
    working_step = int(ochre_step / sig_step)
    duration_min = Duration * 24 * 60
    frequency = f"{t_res}min"
    period = int(duration_min / t_res)

    sim_times = pd.date_range(start=Start, periods=period, freq=frequency)

    required_samples = len(sim_times) * working_step

    if len(reg_signal) < required_samples:
        raise ValueError(
            f"Regulation signal is too short. "
            f"Need {required_samples} samples, "
            f"have {len(reg_signal)}."
        )

    working_sig = []

    count = 0

    for sim_time in sim_times:

        working_sig.append(
            reg_signal["Signal"].iloc[count:count+working_step].mean()
        )

        count += working_step

    working_sig = pd.Series(
        working_sig,
        index=sim_times
    )

    save_sig(working_sig, Start + pd.Timedelta(days=1))

    return working_sig


def save_sig(reg_sig, start_time):

    ts = 15        # minutes per average

    avg_sig = []

    for i in range(0, len(reg_sig), ts):
        avg_sig.append(reg_sig.iloc[i:i+ts].mean())

    avg_sig = pd.Series(avg_sig)

    sim_times = pd.date_range(
        start=start_time,
        periods=len(avg_sig),
        freq="15min"
    )

    saved_sig = pd.DataFrame({
        "Timestamp": sim_times,
        "Signal": avg_sig
    })

    reg_results_dir = os.path.join(
        WORKING_DIR,
        "RegA Signal"
    )

    os.makedirs(reg_results_dir, exist_ok=True)

    saved_sig.to_csv(
        os.path.join(reg_results_dir, "rega_filtered.csv"),
        index=False
    )

    print("file saved!")

def filter_schedules(home_path):
    orig_sched_file = os.path.join(home_path, CSV_ADDRESS)
    filtered_sched_file = os.path.join(home_path, 'filtered_schedules.csv')

    df_sched = pd.read_csv(orig_sched_file)
    valid_schedule_names = set(ALL_SCHEDULE_NAMES.keys())
    filtered_columns = [col for col in df_sched.columns if col in valid_schedule_names]
    dropped_columns = [col for col in df_sched.columns if col not in filtered_columns]
    if dropped_columns:
        print(f"Dropped invalid schedules for {home_path}: {dropped_columns}")

    df_sched_filtered = df_sched[filtered_columns]
    df_sched_filtered.to_csv(filtered_sched_file, index=False)
    return filtered_sched_file

#########################################
# SIMULATION FUNCTION
#########################################

def simulate_home(home_path, weather_file_path, rega_signal):

    filtered_sched_file = filter_schedules(home_path)
    hpxml_file = os.path.join(home_path, XML_ADDRESS)
    results_dir = os.path.join(home_path, "Results")
    os.makedirs(results_dir, exist_ok=True)

    dwelling_args_local = {
        "start_time": Start,
        "time_res": dt.timedelta(minutes=t_res),
        "duration": dt.timedelta(days=Duration),
        "hpxml_file": hpxml_file,
        "hpxml_schedule_file": filtered_sched_file,
        "weather_file": weather_file_path,
        "verbosity": 7,
        #"initialization_time": 1,
        "Equipment": {
            "Water Heating": {
                "Initial Temperature (C)": TinitC, 
                "hp_only_mode": True,
                "Max Tank Temperature": 70,
                "Upper Node": 3,
                "Lower Node": 10,
                "Upper Node Weight": 0.75,
            },
        }
    }
    # quit()

    # Baseline
    base_dwelling = Dwelling(name="HPWH Baseline", **dwelling_args_local)
    for t_base in base_dwelling.sim_times:
        base_ctrl = {"Water Heating": {"Setpoint": TbaselineC, "Deadband": TdeadbandC, "Load Fraction": 1}}
        base_dwelling.update(control_signal=base_ctrl)
    df_base, _, _ = base_dwelling.finalize()

    # Controlled
    sim_dwelling = Dwelling(name="HPWH Controlled", **dwelling_args_local)
    hpwh_unit = sim_dwelling.get_equipment_by_end_use('Water Heating')
    for sim_time in sim_dwelling.sim_times:
        current_setpt = hpwh_unit.schedule.loc[sim_time, 'Water Heating Setpoint (C)']
        control_cmd = determine_hpwh_control(sim_time=sim_time, current_temp_c=current_setpt, rega_sig=rega_signal)
        sim_dwelling.update(control_signal=control_cmd)
    df_ctrl, _, _ = sim_dwelling.finalize()


    df_ctrl = remove_first_day(df_ctrl, Start)
    df_base = remove_first_day(df_base, Start)
    

    CTRL_COLS = ["Time", "Total Electric Power (kW)",
                 "Total Electric Energy (kWh)",
                 "Water Heating Electric Power (kW)",
                 "Water Heating COP (-)",
                 "Water Heating Deadband Upper Limit (C)",
                 "Water Heating Deadband Lower Limit (C)",
                 "Water Heating Heat Pump COP (-)",
                 "Water Heating Control Temperature (C)",
                 "Hot Water Outlet Temperature (C)",
                 "Temperature - Indoor (C)"]
    BASE_COLS = CTRL_COLS
    

    df_ctrl = df_ctrl[[c for c in CTRL_COLS if c in df_ctrl.columns]]

    df_base = df_base[[c for c in BASE_COLS if c in df_base.columns]]
        
    
    df_ctrl.to_csv(os.path.join(results_dir, 'hpwh_controlled.csv'), index=False)
    df_base.to_csv(os.path.join(results_dir, 'hpwh_baseline.csv'), index=False)


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
    os.makedirs(REG_DIR, exist_ok=True)
    try:
        weather_path = Path(WEATHER_DIR)
        weather_path.mkdir(parents=True, exist_ok=True)
        print(f"[INFO] Weather directory ready: {weather_path}")
    except Exception as e:
        print(f"[ERROR] Failed to create directory {weather_path}: {e}")
    
    try:
        reg_path = Path(REG_DIR)
        reg_path.mkdir(parents=True, exist_ok=True)
        print(f"[INFO] Regulation Signal directory ready: {reg_path}")
    except Exception as e:
        print(f"[ERROR] Failed to create directory {reg_path}: {e}")

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

    rega_signal = signal_aggregator_mean()

    # Parallel simulations (threads are Windows-safe)
    # my_schedule is crazy but I wanted to vary schedules within the for loop, so I summed the digits in the home name and mod by 2 to select one of two schedules
    # $ grep -rn "read_psm3(" .
    # ./ochre/utils/schedule.py:186:        df, location = pvlib.iotools.read_psm3(weather_file, map_variables=True)
    # Change to read_nsrdb_psm4 
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(simulate_home, home, WEATHER_FILE, my_schedule[sum(int(char) for char in home if char.isdigit()) % 4]) for home in homes]
        for f in concurrent.futures.as_completed(futures):
            try:
                f.result()  # forces execution and raises exceptions if any
            except Exception as e:
                print("Simulation failed:", e)

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
        df_ctrl_all.to_csv(os.path.join(work_dir, filename + "_controlled.csv"), index=False)

    if all_base:
        df_base_all = pd.concat(all_base, ignore_index=True)
        df_base_all.to_csv(os.path.join(work_dir, filename + "_baseline.csv"), index=False)
    
    print(f"Aggregated CSVs written! {count}")




# CTRL_COLS = ["Time", "Total Electric Power (kW)",
#              "Total Electric Energy (kWh)",
#              "Water Heating Electric Power (kW)",
#              "Water Heating COP (-)",
#              "Water Heating Deadband Upper Limit (C)",
#              "Water Heating Deadband Lower Limit (C)",
#              "Water Heating Heat Pump COP (-)",
#              "Water Heating Control Temperature (C)",
#              "Hot Water Outlet Temperature (C)",
#              "Temperature - Indoor (C)"]
# BASE_COLS = CTRL_COLS

aggregate_results(homes, WORKING_DIR)

