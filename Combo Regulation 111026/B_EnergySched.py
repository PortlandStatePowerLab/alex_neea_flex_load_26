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
import xml.etree.ElementTree as ET
import re
import copy
from ochre import Dwelling
from ochre.utils.schedule import ALL_SCHEDULE_NAMES
import concurrent.futures
from pathlib import Path
import ochre
import numpy as np
import random

#########################################
# USER SETTINGS
#########################################

filename = 'Combo_WH_HVAC_Dryer_EV_Battery_TEST_3'

Input_folder = "Combo HPWH HVAC Dryer EV Almost All Input Files"

# Original OCHRE defaults folder
ochre_dir = Path(ochre.__file__).resolve().parent
DEFAULT_INPUT = ochre_dir / "defaults" / "Input Files"
print("OCHRE installed at:", ochre_dir)
print(DEFAULT_INPUT)

DEFAULT_WEATHER = ochre_dir / "defaults" / "Weather" / "USA_OR_Portland.Intl.AP.726980_TMY3.epw"
# G4100510 is Multnomah county weather station, code will complain this is missing but it doesn't work if you actually try to use it

# working folder
script_dir = os.path.dirname(os.path.abspath(__file__))
fl_dir = os.path.dirname(script_dir)
WORKING_DIR = os.path.dirname(fl_dir)
INPUT_DIR = os.path.join(WORKING_DIR, Input_folder, "bldg")
WEATHER_DIR = os.path.join(WORKING_DIR, "Weather")
WEATHER_FILE = os.path.join(WEATHER_DIR, "USA_OR_Portland.Intl.AP.726980_TMY3.epw")
XML_ADDRESS = "home.xml"
CSV_ADDRESS = "in.schedules.csv"


# Simulation parameters
Start = dt.datetime(2018, 8, 11, 0, 0)
Duration = 2  # days
t_res = 15  # minutes


# WH control parameters (°F)
# GE - Grid Emergency, CP - Critical Peak, Shed
WH_Tcontrol_GEF = 90
WH_Tcontrol_GEdeadbandF = 10
WH_Tcontrol_CPF = 120
WH_Tcontrol_CPdeadbandF = 10
WH_Tcontrol_SHEDF = 126
WH_Tcontrol_deadbandF = 10
# ALU - Advanced load up, LOAD - Load up
WH_Tcontrol_ALUF = 140
WH_Tcontrol_ALUdeadbandF = 2
WH_Tcontrol_LOADF = 130
WH_Tcontrol_LOADdeadbandF = 2

WH_TbaselineF = 130
WH_TdeadbandF = 7
WH_Tinit = 130

# Response time in seconds
WH_RESPONSE_MIN = 30
WH_RESPONSE_MAX = 90

count = 0

# AC control parameters (°F)
# GE - Grid Emergency, CP - Critical Peak, Shed
AC_Tcontrol_GEF = 95
AC_Tcontrol_GEdeadbandF = 4
AC_Tcontrol_CPF = 80
AC_Tcontrol_CPdeadbandF = 4
AC_Tcontrol_SHEDF = 76
AC_Tcontrol_deadbandF = 4
# ALU - Advanced load up, LOAD - Load up
AC_Tcontrol_ALUF = 64
AC_Tcontrol_ALUdeadbandF = 2
AC_Tcontrol_LOADF = 68
AC_Tcontrol_LOADdeadbandF = 2

AC_TbaselineF = 72
AC_TdeadbandF = 2
AC_TinitF = 72

# Heating control parameters (°F)
# GE - Grid Emergency, CP - Critical Peak, Shed
HEAT_Tcontrol_GEF = 45
HEAT_Tcontrol_GEdeadbandF = 4
HEAT_Tcontrol_CPF = 60
HEAT_Tcontrol_CPdeadbandF = 4
HEAT_Tcontrol_SHEDF = 64
HEAT_Tcontrol_deadbandF = 4
# ALU - Advanced load up, LOAD - Load up
HEAT_Tcontrol_ALUF = 76
HEAT_Tcontrol_ALUdeadbandF = 2
HEAT_Tcontrol_LOADF = 72
HEAT_Tcontrol_LOADdeadbandF = 2

HEAT_TbaselineF = 68
HEAT_TdeadbandF = 2
HEAT_TinitF = 68

# Response time in seconds
HVAC_RESPONSE_MIN = 30
HVAC_RESPONSE_MAX = 90

# Dryer duty cycle parameters, dryers can't load up only curtail power
dryer_duty_cycle_shed = 0.5
dryer_duty_cycle_cp = 0.25
dryer_duty_cycle_ge = 0

# EV Control Settings
DEFAULT_CHARGER_POWER_KW = 11.5 # Fallback 1.6 for Level 1, 5.6 for Level 2 (Dynamically checked per home below)
DEFAULT_CAPACITY_KWH = 60.0 # Fallback capacity if missing from HPXML
EV_SHED_PCT = 0.5
EV_CP_PCT = 0.25
EV_GE_PCT = 0

# Battery Control Settings
BATTERY_PARAMS = {
    "capacity_kwh": 10,         # Usable energy capacity in kWh
    "capacity": 1.0,            # Max continuous power rating in kW
    "efficiency": 0.98,         # Discharging efficiency
    "efficiency_charge": 0.98,  # Charging efficiency
    "soc_init": 0.5,            # Start at 50% SOC
    "soc_min": 0.0,             # Minimum allowable SOC
    "soc_max": 1.0,             # Maximum allowable SOC
}

# Control commands in kW (+ is charging/Load Up, - is discharging/Shed)
P_Battery_ALU_KW = 1.0 * BATTERY_PARAMS['capacity']        # Charge battery ALU
P_Battery_LU_KW = 0.25 * BATTERY_PARAMS['capacity']        # Charge battery LU
P_Battery_SHED_KW = -0.25 * BATTERY_PARAMS['capacity']     # Discharge battery Shed
P_Battery_CP_KW = -0.5 * BATTERY_PARAMS['capacity']        # Discharge battery CP
P_Battery_GE_KW = -1.0 * BATTERY_PARAMS['capacity']        # Discharge battery GE
P_Battery_IDLE_KW = 0.0                                    # Idle


# ---------------------------------------------------------
# LOAD DEVICES FROM CSV
# ---------------------------------------------------------
devices_file = os.path.join(script_dir, "B0_Devices.csv")
try:
    df_devices = pd.read_csv(devices_file)
    # Convert to dictionary mapping 'Device' to 'Simulation'
    device_sim_map = dict(zip(df_devices['Device'], df_devices['Simulation']))
except FileNotFoundError:
    print(f"[WARNING] {devices_file} not found. Defaulting to OFF.")
    device_sim_map = {}

WH_SIMULATION = device_sim_map.get("WH", "OFF")
HVAC_SIMULATION = device_sim_map.get("HVAC", "OFF")
DRYER_SIMULATION = device_sim_map.get("Dryer", "OFF")
EV_SIMULATION = device_sim_map.get("EV", "OFF")
BATTERY_SIMULATION = device_sim_map.get("Battery", "OFF")


# ---------------------------------------------------------
# LOAD COMMANDS SCHEDULE FROM CSV
# ---------------------------------------------------------
schedule_file = os.path.join(script_dir, "B0_Commands_Schedule.csv")
my_schedule1 = {}

try:
    df_sched = pd.read_csv(schedule_file)
    
    for index, row in df_sched.iterrows():
        command = str(row['Command']).strip()
        on_off = str(row['OnOff']).strip().upper()
        
        if on_off == 'ON':
            # -- Parse RAMP IN --
            start_rin_str = str(row['START RAMP IN']).strip()
            dur_rin = float(row['DURATION RAMP IN'])
            
            t_start_rin = dt.datetime.strptime(start_rin_str, '%H:%M')
            t_end_rin = t_start_rin + dt.timedelta(hours=dur_rin)
            
            my_schedule1[f"{command}_rampin_start"] = t_start_rin.strftime('%H:%M')
            my_schedule1[f"{command}_rampin_end"] = t_end_rin.strftime('%H:%M')
            
            # -- Parse RAMP OUT --
            start_rout_str = str(row['START RAMP OUT']).strip()
            dur_rout = float(row['DURATION RAMP OUT'])
            
            t_start_rout = dt.datetime.strptime(start_rout_str, '%H:%M')
            t_end_rout = t_start_rout + dt.timedelta(hours=dur_rout)
            
            my_schedule1[f"{command}_rampout_start"] = t_start_rout.strftime('%H:%M')
            my_schedule1[f"{command}_rampout_end"] = t_end_rout.strftime('%H:%M')
            
except FileNotFoundError:
    print(f"[ERROR] {schedule_file} not found. The simulation may fail.")

def shift_time(time_str, minutes):
    """Helper function to add minutes to an 'HH:MM' string."""
    delta_t = dt.datetime.strptime(time_str, '%H:%M')
    new_delta_t = delta_t + dt.timedelta(minutes=minutes)
    return new_delta_t.strftime('%H:%M')

bins = 17

#########################################
# STAGGER SCHEDULES FOR RAMPING
#########################################

def create_home_schedule(base_sched, bins, home_idx):
    """
    Calculates staggered start/end timedeltas for a specific home 
    distributed across the defined ramp-in and ramp-out periods.
    """
    bin_idx = home_idx % bins
    
    # Calculate the fraction of the ramp duration this bin represents.
    # We use (bins - 1) so that the first bin is at the exact start (0.0), 
    # and the last bin is at the exact end (1.0) of the ramp period.
    ramp_fraction = (bin_idx / (bins - 1)) if bins > 1 else 0

    def parse_time(time_str):
        t = dt.datetime.strptime(time_str, '%H:%M')
        return pd.Timedelta(hours=t.hour, minutes=t.minute)

    home_schedule = {}
    
    # Process all combinations of Time-of-Day (M/E) and Modes
    times_of_day = ['M', 'E']
    modes = ['ALU', 'LU', 'S', 'CP', 'GE']

    for tod in times_of_day:
        for mode in modes:
            prefix = f"{tod}_{mode}" # e.g. "M_ALU"
            
            # --- RAMP IN (Start of command) ---
            rin_start_str = base_sched.get(f"{prefix}_rampin_start", "00:00")
            rin_end_str = base_sched.get(f"{prefix}_rampin_end", rin_start_str)
            
            rin_start_td = parse_time(rin_start_str)
            rin_end_td = parse_time(rin_end_str)
            rin_duration = rin_end_td - rin_start_td
            
            # Interpolate ramp-in time based on bin position
            home_start_td = rin_start_td + (rin_duration * ramp_fraction)

            # --- RAMP OUT (End of command) ---
            rout_start_str = base_sched.get(f"{prefix}_rampout_start", "00:00")
            rout_end_str = base_sched.get(f"{prefix}_rampout_end", rout_start_str)
            
            rout_start_td = parse_time(rout_start_str)
            rout_end_td = parse_time(rout_end_str)
            rout_duration = rout_end_td - rout_start_td
            
            # Interpolate ramp-out time based on bin position
            home_end_td = rout_start_td + (rout_duration * ramp_fraction)

            home_schedule[prefix] = (home_start_td, home_end_td)

    # print(home_idx)
    # print(bin_idx)
    # print(home_schedule)
    return home_schedule


#########################################
# TEMPERATURE CONVERSIONS F to C
#########################################

def f_to_c(temp_f): 
    return (temp_f - 32) * 5/9

def f_to_c_DB(temp_f):
    return 5/9 * temp_f

WH_Tcontrol_GEC = f_to_c(WH_Tcontrol_GEF)
WH_Tcontrol_GEdeadbandC = f_to_c_DB(WH_Tcontrol_GEdeadbandF)
WH_Tcontrol_CPC = f_to_c(WH_Tcontrol_CPF)
WH_Tcontrol_CPdeadbandC = f_to_c_DB(WH_Tcontrol_CPdeadbandF)
WH_Tcontrol_SHEDC = f_to_c(WH_Tcontrol_SHEDF)
WH_Tcontrol_deadbandC = f_to_c_DB(WH_Tcontrol_deadbandF)

WH_Tcontrol_ALUC = f_to_c(WH_Tcontrol_ALUF)
WH_Tcontrol_ALUdeadbandC = f_to_c_DB(WH_Tcontrol_ALUdeadbandF)
WH_Tcontrol_LOADC = f_to_c(WH_Tcontrol_LOADF)
WH_Tcontrol_LOADdeadbandC = f_to_c_DB(WH_Tcontrol_LOADdeadbandF)

WH_TbaselineC = f_to_c(WH_TbaselineF)
WH_TdeadbandC = f_to_c_DB(WH_TdeadbandF)
WH_TinitC = f_to_c(WH_Tinit)


AC_Tcontrol_GEC = f_to_c(AC_Tcontrol_GEF)
AC_Tcontrol_GEdeadbandC = f_to_c_DB(AC_Tcontrol_GEdeadbandF)
AC_Tcontrol_CPC = f_to_c(AC_Tcontrol_CPF)
AC_Tcontrol_CPdeadbandC = f_to_c_DB(AC_Tcontrol_CPdeadbandF)
AC_Tcontrol_SHEDC = f_to_c(AC_Tcontrol_SHEDF)
AC_Tcontrol_deadbandC = f_to_c_DB(AC_Tcontrol_deadbandF)

AC_Tcontrol_ALUC = f_to_c(AC_Tcontrol_ALUF)
AC_Tcontrol_ALUdeadbandC = f_to_c_DB(AC_Tcontrol_ALUdeadbandF)
AC_Tcontrol_LOADC = f_to_c(AC_Tcontrol_LOADF)
AC_Tcontrol_LOADdeadbandC = f_to_c_DB(AC_Tcontrol_LOADdeadbandF)

AC_TbaselineC = f_to_c(AC_TbaselineF)
AC_TdeadbandC = f_to_c_DB(AC_TdeadbandF)
AC_TinitC = f_to_c(AC_TinitF)


HEAT_Tcontrol_GEC = f_to_c(HEAT_Tcontrol_GEF)
HEAT_Tcontrol_GEdeadbandC = f_to_c_DB(HEAT_Tcontrol_GEdeadbandF)
HEAT_Tcontrol_CPC = f_to_c(HEAT_Tcontrol_CPF)
HEAT_Tcontrol_CPdeadbandC = f_to_c_DB(HEAT_Tcontrol_CPdeadbandF)
HEAT_Tcontrol_SHEDC = f_to_c(HEAT_Tcontrol_SHEDF)
HEAT_Tcontrol_deadbandC = f_to_c_DB(HEAT_Tcontrol_deadbandF)

HEAT_Tcontrol_ALUC = f_to_c(HEAT_Tcontrol_ALUF)
HEAT_Tcontrol_ALUdeadbandC = f_to_c_DB(HEAT_Tcontrol_ALUdeadbandF)
HEAT_Tcontrol_LOADC = f_to_c(HEAT_Tcontrol_LOADF)
HEAT_Tcontrol_LOADdeadbandC = f_to_c_DB(HEAT_Tcontrol_LOADdeadbandF)

HEAT_TbaselineC = f_to_c(HEAT_TbaselineF)
HEAT_TdeadbandC = f_to_c_DB(HEAT_TdeadbandF)
HEAT_TinitC = f_to_c(HEAT_TinitF)

#########################################
# EV PARSER HELPERS
#########################################

def get_ev_charger_power(hpxml_path, default_kw=20):
    """
    Parses the home's HPXML file to determine the power the EV charger draws
    """
    try:
        tree = ET.parse(hpxml_path)
        root = tree.getroot()
        
        # Remove namespaces for easier tag matching
        for elem in root.iter():
            if '}' in elem.tag:
                elem.tag = elem.tag.split('}', 1)[1]
                
        for charger in root.findall('.//ElectricVehicleCharger'):
            charge_elem = charger.find('ChargingPower')
            
            if charge_elem is not None and charge_elem.text:
                return float(charge_elem.text) / 1000
                
    except Exception as e:
        print(f"[WARNING] Failed to parse EV charger level from {hpxml_path}. Using default {default_kw}. Error: {e}")
    
    return default_kw

def get_ev_capacity_or_range(hpxml_path, default_capacity_kwh=60.0):
    """
    Parses the home's HPXML file to determine the EV's usable or nominal battery capacity.
    Returns capacity in kWh.
    """
    try:
        tree = ET.parse(hpxml_path)
        root = tree.getroot()
        
        # Remove namespaces for easier tag matching
        for elem in root.iter():
            if '}' in elem.tag:
                elem.tag = elem.tag.split('}', 1)[1]
                
        # Search for Battery element under ElectricVehicle/Vehicle
        for battery in root.findall('.//Battery'):
            # Prefer UsableCapacity, fallback to NominalCapacity
            usable = battery.find('UsableCapacity/Value')
            if usable is not None and usable.text:
                return float(usable.text)
                
            nominal = battery.find('NominalCapacity/Value')
            if nominal is not None and nominal.text:
                return float(nominal.text)
                
    except Exception as e:
        print(f"[WARNING] Failed to parse EV capacity from {hpxml_path}. Using default {default_capacity_kwh} kWh. Error: {e}")
        
    return default_capacity_kwh

#########################################
# CONTROL FUNCTION
#########################################

def determine_control(sim_time, current_temp_c, home_schedule_td, home_charger_kw=None, 
                      wh_delay=None, hvac_delay=None, **kwargs):
    # Default offsets to 0 seconds if not provided
    wh_delay = wh_delay if wh_delay is not None else pd.Timedelta(seconds=0)
    hvac_delay = hvac_delay if hvac_delay is not None else pd.Timedelta(seconds=0)

    # Initialize control signal dictionary
    ctrl_signal = {}

    # Add Water Heating if simulated
    if WH_SIMULATION == "ON":
        ctrl_signal['Water Heating'] = {
            'Setpoint': WH_TbaselineC,
            'Deadband': WH_TdeadbandC,
            'Load Fraction': 1,
        }

    # Add HVAC if simulated, checking the month to separate Heating vs Cooling
    # Let's assume May (5) through Sept (9) is Cooling Season in Portland
    is_cooling_season = sim_time.month in [5, 6, 7, 8, 9]

    if HVAC_SIMULATION == "ON":
        if is_cooling_season:
            # Normal cooling control
            ctrl_signal['HVAC Cooling'] = {
                'Setpoint': AC_TbaselineC,
                'Deadband': AC_TdeadbandC,
                'Load Fraction': 1,
            }
            # Suppress heating by pushing setpoint extremely low
            ctrl_signal['HVAC Heating'] = {
                'Setpoint': HEAT_Tcontrol_GEC,
                'Deadband': HEAT_TdeadbandC,
                'Load Fraction': 1,
            }
        else:
            # Normal heating control
            ctrl_signal['HVAC Heating'] = {
                'Setpoint': HEAT_TbaselineC,
                'Deadband': HEAT_TdeadbandC,
                'Load Fraction': 1,
            }
            # Suppress cooling by pushing setpoint extremely high
            ctrl_signal['HVAC Cooling'] = {
                'Setpoint': AC_Tcontrol_GEC,
                'Deadband': AC_TdeadbandC,
                'Load Fraction': 1,
            }

    # Add dryers if simulated
    if DRYER_SIMULATION == "ON":
        ctrl_signal['Clothes Dryer'] = {
            'Load Fraction': 1  # 1 = Normal schedule operation
        }

    # Add batteries if simulated
    if BATTERY_SIMULATION == "ON":
        ctrl_signal['Battery'] = {
            'P Setpoint': P_Battery_IDLE_KW
        }


    midnight = pd.to_datetime(sim_time.date())

    # Define modes in priority order: 
    # (Mode Name, WH_SP, WH_DB, AC_SP, AC_DB, HEAT_SP, HEAT_DB)
    modes = [
        ('ALU', WH_Tcontrol_ALUC, WH_Tcontrol_ALUdeadbandC, AC_Tcontrol_ALUC, AC_Tcontrol_ALUdeadbandC, HEAT_Tcontrol_ALUC, HEAT_Tcontrol_ALUdeadbandC),
        ('LU',  WH_Tcontrol_LOADC, WH_Tcontrol_LOADdeadbandC, AC_Tcontrol_LOADC, AC_Tcontrol_LOADdeadbandC, HEAT_Tcontrol_LOADC, HEAT_Tcontrol_LOADdeadbandC),
        ('S',   WH_Tcontrol_SHEDC, WH_Tcontrol_deadbandC, AC_Tcontrol_SHEDC, AC_Tcontrol_deadbandC, HEAT_Tcontrol_SHEDC, HEAT_Tcontrol_deadbandC),
        ('CP',  WH_Tcontrol_CPC, WH_Tcontrol_CPdeadbandC, AC_Tcontrol_CPC, AC_Tcontrol_CPdeadbandC, HEAT_Tcontrol_CPC, HEAT_Tcontrol_CPdeadbandC),
        ('GE',  WH_Tcontrol_GEC, WH_Tcontrol_GEdeadbandC, AC_Tcontrol_GEC, AC_Tcontrol_GEdeadbandC, HEAT_Tcontrol_GEC, HEAT_Tcontrol_GEdeadbandC)
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
    if WH_SIMULATION == "ON" and wh_mode:
        _, wh_sp, wh_db, _, _, _, _ = wh_mode
        ctrl_signal['Water Heating'].update({'Setpoint': wh_sp, 'Deadband': wh_db})

    # Apply HVAC setpoints
    if HVAC_SIMULATION == "ON" and hvac_mode:
        _, _, _, ac_sp, ac_db, heat_sp, heat_db = hvac_mode
        if is_cooling_season:
            ctrl_signal['HVAC Cooling'].update({'Setpoint': ac_sp, 'Deadband': ac_db})
        else:
            ctrl_signal['HVAC Heating'].update({'Setpoint': heat_sp, 'Deadband': heat_db})

    # Add EV logic based on unshifted/base schedule
    if EV_SIMULATION == "ON" and home_charger_kw is not None:
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
        fraction = EV_SHED_PCT if ev_state == 'Shed' else (EV_CP_PCT if ev_state == 'CP' else (EV_GE_PCT if ev_state == 'GE' else 1.0))
        commanded_kw = abs(fraction * home_charger_kw)
        ctrl_signal['EV'] = {'Max Power': max(commanded_kw, 0.001)}

    # Add battery logic base schedule
    if BATTERY_SIMULATION == "ON":
        battery_state = base_mode[0] if base_mode else 'Normal'
        battery_p_map = {
            'ALU': P_Battery_ALU_KW,
            'LU': P_Battery_LU_KW,
            'S': P_Battery_SHED_KW,
            'CP': P_Battery_CP_KW,
            'GE': P_Battery_GE_KW
        }
        battery_p = battery_p_map.get(battery_state, P_Battery_IDLE_KW)
        ctrl_signal['Battery'] = {'P Setpoint': battery_p}

    return ctrl_signal

#########################################
# SCHEDULE FILTERING
#########################################

def filter_schedules(home_path):
    orig_sched_file = os.path.join(home_path, CSV_ADDRESS)
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
    orig_sched_file = os.path.join(home_path, CSV_ADDRESS)
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
        'S': dryer_duty_cycle_shed,
        'CP': dryer_duty_cycle_cp,
        'GE': dryer_duty_cycle_ge
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
    base_sched_file, ctrl_sched_file = prepare_schedules(home_path, schedule_cfg, t_res)
    
    hpxml_file = os.path.join(home_path, XML_ADDRESS)
    results_dir = os.path.join(home_path, "Results")
    os.makedirs(results_dir, exist_ok=True)

    equipment = {}

    if WH_SIMULATION == "ON":
        equipment["Water Heating"] = {
                "Initial Temperature (C)": WH_TinitC, 
                "hp_only_mode": True,
                "Max Tank Temperature": 70,
                "Upper Node": 3,
                "Lower Node": 10,
                "Upper Node Weight": 0.75,
        }

    if BATTERY_SIMULATION == "ON":
        equipment["Battery"] = BATTERY_PARAMS

    home_charger_kw = None
    if EV_SIMULATION == "ON":
        home_charger_kw = get_ev_charger_power(hpxml_file, DEFAULT_CHARGER_POWER_KW)
        home_ev_capacity = get_ev_capacity_or_range(hpxml_file, DEFAULT_CAPACITY_KWH)
        
        if home_charger_kw > 8:
            home_charger = "Level 2"
        else:
            home_charger = "Level 1"
            
        equipment["EV"] = {
            "vehicle_type": "BEV",
            "capacity": home_ev_capacity,
            "charging_level": home_charger,
            "max_power": home_charger_kw
        }

    # Extract digits from the home folder name to use as a seed
    home_name = os.path.basename(home_path)
    home_num_str = re.sub(r'\D', '', home_name)
    home_seed = int(home_num_str) if home_num_str else 0

    # 2. Remove "hpxml_schedule_file" from these shared arguments
    dwelling_args_local = {
        "start_time": Start,
        "time_res": dt.timedelta(minutes=t_res),
        "duration": dt.timedelta(days=Duration),
        "hpxml_file": hpxml_file,
        "weather_file": weather_file_path,
        "verbosity": 7,
        "seed": home_seed,
        "Equipment": equipment
    }

    # --- Baseline Simulation ---
    # 3. Explicitly pass the baseline schedule file to the baseline dwelling
    random.seed(home_seed)
    np.random.seed(home_seed)
    base_dwelling = Dwelling(name="Home Baseline", hpxml_schedule_file=base_sched_file, **copy.deepcopy(dwelling_args_local))
    
    for t_base in base_dwelling.sim_times:
        # Build baseline control dynamically so we don't crash if things are OFF
        base_ctrl = {}
        if WH_SIMULATION == "ON":
            base_ctrl["Water Heating"] = {"Setpoint": WH_TbaselineC, "Deadband": WH_TdeadbandC, "Load Fraction": 1}
        
        if HVAC_SIMULATION == "ON":
            base_ctrl["HVAC Cooling"] = {"Setpoint": AC_TbaselineC, "Deadband": AC_TdeadbandC, "Load Fraction": 1}
            base_ctrl["HVAC Heating"] = {"Setpoint": HEAT_TbaselineC, "Deadband": HEAT_TdeadbandC, "Load Fraction": 1}
        
        if EV_SIMULATION == "ON" and home_charger_kw is not None:
            base_ctrl["EV"] = {"Max Power": home_charger_kw}
                
        base_dwelling.update(control_signal=base_ctrl)
    df_base, _, _ = base_dwelling.finalize()

    # Generate random response time delays for WH and HVAC for this home
    wh_delay_sec = random.uniform(WH_RESPONSE_MIN, WH_RESPONSE_MAX)
    hvac_delay_sec = random.uniform(HVAC_RESPONSE_MIN, HVAC_RESPONSE_MAX)
    
    wh_delay = pd.Timedelta(seconds=wh_delay_sec)
    hvac_delay = pd.Timedelta(seconds=hvac_delay_sec)

    # --- Controlled Simulation ---
    # 4. Explicitly pass the controlled (shifted) schedule file to the controlled dwelling
    random.seed(home_seed)
    np.random.seed(home_seed)
    sim_dwelling = Dwelling(name="Home Controlled", hpxml_schedule_file=ctrl_sched_file, **copy.deepcopy(dwelling_args_local))
    
    # Get HPWH unit only if WH_SIMULATION is ON
    hpwh_unit = None
    if WH_SIMULATION == "ON":
        hpwh_unit = sim_dwelling.get_equipment_by_end_use('Water Heating')
        
    for sim_time in sim_dwelling.sim_times:
        # Provide a default temp if WH is off so determine_control still works
        current_setpt = WH_TinitC 
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
    df_ctrl = remove_first_day(df_ctrl, Start)
    df_base = remove_first_day(df_base, Start)
    
    # Dynamically build output columns based on what's turned ON
    CTRL_COLS = ["Time", "Total Electric Power (kW)", "Total Electric Energy (kWh)"]
    if WH_SIMULATION == "ON":
        CTRL_COLS.append("Water Heating Electric Power (kW)")
    if HVAC_SIMULATION == "ON":
        CTRL_COLS.extend(["HVAC Heating Electric Power (kW)", "HVAC Cooling Electric Power (kW)"])
    if DRYER_SIMULATION == "ON":
        CTRL_COLS.append("Clothes Dryer Electric Power (kW)")
    if EV_SIMULATION == "ON":
        CTRL_COLS.append("EV Electric Power (kW)")
        CTRL_COLS.append("EV SOC (-)")
    if BATTERY_SIMULATION == "ON":
        CTRL_COLS.append("Battery Electric Power (kW)")
        CTRL_COLS.append("Battery SOC (-)")
    
    # Keep only the columns that actually exist in the DataFrame
    df_ctrl = df_ctrl[[c for c in CTRL_COLS if c in df_ctrl.columns]]
    df_base = df_base[[c for c in CTRL_COLS if c in df_base.columns]]
        
    df_ctrl.to_csv(os.path.join(results_dir, 'home_controlled.csv'), index=False)
    df_base.to_csv(os.path.join(results_dir, 'home_baseline.csv'), index=False)

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

failcount = 0

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
            home_sched_td = create_home_schedule(my_schedule1, bins=bins, home_idx=home_num)
            
            # Submit to the thread pool
            futures.append(executor.submit(simulate_home, home, WEATHER_FILE, home_sched_td))

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
        df_ctrl_all.to_csv(os.path.join(work_dir, filename + "_controlled.csv"), index=False)

    if all_base:
        df_base_all = pd.concat(all_base, ignore_index=True)
        df_base_all.to_csv(os.path.join(work_dir, filename + "_baseline.csv"), index=False)
    
    print(f"Aggregated CSVs written! {count}")

if __name__ == "__main__":
    aggregate_results(homes, WORKING_DIR)