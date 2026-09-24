"""Shared setup for Combo baseline (B1) and regulation (B2).

init_home returns an independent dwelling and home_info, including the actual
participating end uses and reproducible response delays. Use
B_ControlSignals.control_for_home to translate NORMAL baseline operation or
queued controlled commands. Initialization is serial because OCHRE seeds global
random generators.

Configuration keys preserve the original EnergySched setting names. Edit user
settings inside load_configuration; Celsius values are derived there. Importing
this module does not read configuration CSVs or create/run dwellings.
"""

import os
import datetime as dt
import pandas as pd
import xml.etree.ElementTree as ET
import re
import copy
from ochre import Dwelling
from pathlib import Path
import ochre
import numpy as np
import random

FLEX_END_USES = {
    "Water Heating": ("WH", "WH_SIMULATION"),
    "HVAC Heating": ("HVAC", "HVAC_SIMULATION"),
    "HVAC Cooling": ("HVAC", "HVAC_SIMULATION"),
    "Clothes Dryer": ("Dryer", "DRYER_SIMULATION"),
    "EV": ("EV", "EV_SIMULATION"),
    "Battery": ("Battery", "BATTERY_SIMULATION"),
}


def response_delays(home_seed, config):
    """Private RNG: delay assignment never consumes OCHRE's random stream."""
    delays = {}
    for device, prefix in (("WH", "WH"), ("HVAC", "HVAC")):
        low, high = float(config[prefix + "_RESPONSE_MIN"]), float(config[prefix + "_RESPONSE_MAX"])
        if not np.isfinite([low, high]).all() or not 0 <= low <= high:
            raise ValueError(f"Invalid {prefix} response delay bounds")
        rng = random.Random(f"{home_seed}:{device}:response-delay")
        delays[device] = rng.uniform(low, high)
    return delays


def load_configuration():
    #########################################
    # USER SETTINGS
    #########################################

    filename = 'Combo_WH_HVAC_Dryer_EV_Battery_TEST_3'

    Input_folder = "Combo All Input Files"

    # Original OCHRE defaults folder
    ochre_dir = Path(ochre.__file__).resolve().parent
    DEFAULT_INPUT = ochre_dir / "defaults" / "Input Files"
    # print("OCHRE installed at:", ochre_dir)
    # print(DEFAULT_INPUT)

    DEFAULT_WEATHER = ochre_dir / "defaults" / "Weather" / "USA_OR_Portland.Intl.AP.726980_TMY3.epw"
    # G4100510 is Multnomah county weather station, code will complain this is missing but it doesn't work if you actually try to use it

    # working folder
    script_dir = os.path.dirname(os.path.abspath(__file__))
    fl_dir = os.path.dirname(script_dir)
    WORKING_DIR = os.path.dirname(fl_dir)
    INPUT_DIR = os.path.join(fl_dir, Input_folder, "bldg")
    WEATHER_DIR = os.path.join(fl_dir, "Weather")
    WEATHER_FILE = os.path.join(WEATHER_DIR, "USA_OR_Portland.Intl.AP.726980_TMY3.epw")
    XML_ADDRESS = "home.xml"
    CSV_ADDRESS = "in.schedules.csv"

    REG_TYPE = 'RegA'
    # The calculator-owned signal folder is the direct parent of HPWH.
    REG_DIR = os.path.join(script_dir, "Reg Sig")
    REG_ADDRESS = f"{REG_TYPE}-ochre.csv"

    # Simulation parameters
    Start = dt.datetime(2018, 8, 11, 0, 0)
    Duration = 1  # days
    t_res = 1  # minutes

    # NUM_HOMES = 10

    # B3 receives its directional regulation capacities from B2's baseline run.

    # Dispatch and comfort settings.  With a one-minute timestep, five minutes is
    # a conservative initial minimum command duration.  A home is always released
    # if the regulation request reverses direction or returns to zero.
    MIN_HOLD_MINUTES = 5
    MIN_HOLD_STEPS = max(1, round(MIN_HOLD_MINUTES / t_res))
    CONTROL_INTERVAL_MINUTES = 1
    CONTROL_INTERVAL_STEPS = max(1, round(CONTROL_INTERVAL_MINUTES / t_res))
    ACTIVE_POWER_THRESHOLD_KW = 0.1
    EXPECTED_ON_POWER_KW = 0.5
    FEEDBACK_GAIN = 0.3
    TRACKING_DEADBAND_KW = 0.25
    MAX_RESPONSE_CHANGE_KW_PER_INTERVAL = 10

    # WH control parameters (Â°F)
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

    # AC control parameters (Â°F)
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

    # Heating control parameters (Â°F)
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

    #########################################
    # TEMPERATURE CONVERSIONS F to C
    #########################################

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


    # Cancel if failures > discovered homes - this target.
    # The inclusive comparison requires MORE than this many successes.
    MIN_INITIALIZED_HOMES = 430
    RELIABLE_CAPACITY_QUANTILE = 0.10

    # Keep existing setting names so callers can migrate incrementally.
    return {
        "filename": filename,
        "Input_folder": Input_folder,
        "DEFAULT_INPUT": DEFAULT_INPUT,
        "DEFAULT_WEATHER": DEFAULT_WEATHER,
        "script_dir": script_dir,
        "fl_dir": fl_dir,
        "WORKING_DIR": WORKING_DIR,
        "INPUT_DIR": INPUT_DIR,
        "WEATHER_DIR": WEATHER_DIR,
        "WEATHER_FILE": WEATHER_FILE,
        "XML_ADDRESS": XML_ADDRESS,
        "CSV_ADDRESS": CSV_ADDRESS,
        "Start": Start,
        "Duration": Duration,
        "t_res": t_res,
        "WH_Tcontrol_GEF": WH_Tcontrol_GEF,
        "WH_Tcontrol_GEdeadbandF": WH_Tcontrol_GEdeadbandF,
        "WH_Tcontrol_CPF": WH_Tcontrol_CPF,
        "WH_Tcontrol_CPdeadbandF": WH_Tcontrol_CPdeadbandF,
        "WH_Tcontrol_SHEDF": WH_Tcontrol_SHEDF,
        "WH_Tcontrol_deadbandF": WH_Tcontrol_deadbandF,
        "WH_Tcontrol_ALUF": WH_Tcontrol_ALUF,
        "WH_Tcontrol_ALUdeadbandF": WH_Tcontrol_ALUdeadbandF,
        "WH_Tcontrol_LOADF": WH_Tcontrol_LOADF,
        "WH_Tcontrol_LOADdeadbandF": WH_Tcontrol_LOADdeadbandF,
        "WH_TbaselineF": WH_TbaselineF,
        "WH_TdeadbandF": WH_TdeadbandF,
        "WH_Tinit": WH_Tinit,
        "WH_RESPONSE_MIN": WH_RESPONSE_MIN,
        "WH_RESPONSE_MAX": WH_RESPONSE_MAX,
        "AC_Tcontrol_GEF": AC_Tcontrol_GEF,
        "AC_Tcontrol_GEdeadbandF": AC_Tcontrol_GEdeadbandF,
        "AC_Tcontrol_CPF": AC_Tcontrol_CPF,
        "AC_Tcontrol_CPdeadbandF": AC_Tcontrol_CPdeadbandF,
        "AC_Tcontrol_SHEDF": AC_Tcontrol_SHEDF,
        "AC_Tcontrol_deadbandF": AC_Tcontrol_deadbandF,
        "AC_Tcontrol_ALUF": AC_Tcontrol_ALUF,
        "AC_Tcontrol_ALUdeadbandF": AC_Tcontrol_ALUdeadbandF,
        "AC_Tcontrol_LOADF": AC_Tcontrol_LOADF,
        "AC_Tcontrol_LOADdeadbandF": AC_Tcontrol_LOADdeadbandF,
        "AC_TbaselineF": AC_TbaselineF,
        "AC_TdeadbandF": AC_TdeadbandF,
        "AC_TinitF": AC_TinitF,
        "HEAT_Tcontrol_GEF": HEAT_Tcontrol_GEF,
        "HEAT_Tcontrol_GEdeadbandF": HEAT_Tcontrol_GEdeadbandF,
        "HEAT_Tcontrol_CPF": HEAT_Tcontrol_CPF,
        "HEAT_Tcontrol_CPdeadbandF": HEAT_Tcontrol_CPdeadbandF,
        "HEAT_Tcontrol_SHEDF": HEAT_Tcontrol_SHEDF,
        "HEAT_Tcontrol_deadbandF": HEAT_Tcontrol_deadbandF,
        "HEAT_Tcontrol_ALUF": HEAT_Tcontrol_ALUF,
        "HEAT_Tcontrol_ALUdeadbandF": HEAT_Tcontrol_ALUdeadbandF,
        "HEAT_Tcontrol_LOADF": HEAT_Tcontrol_LOADF,
        "HEAT_Tcontrol_LOADdeadbandF": HEAT_Tcontrol_LOADdeadbandF,
        "HEAT_TbaselineF": HEAT_TbaselineF,
        "HEAT_TdeadbandF": HEAT_TdeadbandF,
        "HEAT_TinitF": HEAT_TinitF,
        "HVAC_RESPONSE_MIN": HVAC_RESPONSE_MIN,
        "HVAC_RESPONSE_MAX": HVAC_RESPONSE_MAX,
        "dryer_duty_cycle_shed": dryer_duty_cycle_shed,
        "dryer_duty_cycle_cp": dryer_duty_cycle_cp,
        "dryer_duty_cycle_ge": dryer_duty_cycle_ge,
        "DEFAULT_CHARGER_POWER_KW": DEFAULT_CHARGER_POWER_KW,
        "DEFAULT_CAPACITY_KWH": DEFAULT_CAPACITY_KWH,
        "EV_SHED_PCT": EV_SHED_PCT,
        "EV_CP_PCT": EV_CP_PCT,
        "EV_GE_PCT": EV_GE_PCT,
        "BATTERY_PARAMS": BATTERY_PARAMS,
        "P_Battery_ALU_KW": P_Battery_ALU_KW,
        "P_Battery_LU_KW": P_Battery_LU_KW,
        "P_Battery_SHED_KW": P_Battery_SHED_KW,
        "P_Battery_CP_KW": P_Battery_CP_KW,
        "P_Battery_GE_KW": P_Battery_GE_KW,
        "P_Battery_IDLE_KW": P_Battery_IDLE_KW,
        "WH_SIMULATION": WH_SIMULATION,
        "HVAC_SIMULATION": HVAC_SIMULATION,
        "DRYER_SIMULATION": DRYER_SIMULATION,
        "EV_SIMULATION": EV_SIMULATION,
        "BATTERY_SIMULATION": BATTERY_SIMULATION,
        "WH_Tcontrol_GEC": WH_Tcontrol_GEC,
        "WH_Tcontrol_GEdeadbandC": WH_Tcontrol_GEdeadbandC,
        "WH_Tcontrol_CPC": WH_Tcontrol_CPC,
        "WH_Tcontrol_CPdeadbandC": WH_Tcontrol_CPdeadbandC,
        "WH_Tcontrol_SHEDC": WH_Tcontrol_SHEDC,
        "WH_Tcontrol_deadbandC": WH_Tcontrol_deadbandC,
        "WH_Tcontrol_ALUC": WH_Tcontrol_ALUC,
        "WH_Tcontrol_ALUdeadbandC": WH_Tcontrol_ALUdeadbandC,
        "WH_Tcontrol_LOADC": WH_Tcontrol_LOADC,
        "WH_Tcontrol_LOADdeadbandC": WH_Tcontrol_LOADdeadbandC,
        "WH_TbaselineC": WH_TbaselineC,
        "WH_TdeadbandC": WH_TdeadbandC,
        "WH_TinitC": WH_TinitC,
        "AC_Tcontrol_GEC": AC_Tcontrol_GEC,
        "AC_Tcontrol_GEdeadbandC": AC_Tcontrol_GEdeadbandC,
        "AC_Tcontrol_CPC": AC_Tcontrol_CPC,
        "AC_Tcontrol_CPdeadbandC": AC_Tcontrol_CPdeadbandC,
        "AC_Tcontrol_SHEDC": AC_Tcontrol_SHEDC,
        "AC_Tcontrol_deadbandC": AC_Tcontrol_deadbandC,
        "AC_Tcontrol_ALUC": AC_Tcontrol_ALUC,
        "AC_Tcontrol_ALUdeadbandC": AC_Tcontrol_ALUdeadbandC,
        "AC_Tcontrol_LOADC": AC_Tcontrol_LOADC,
        "AC_Tcontrol_LOADdeadbandC": AC_Tcontrol_LOADdeadbandC,
        "AC_TbaselineC": AC_TbaselineC,
        "AC_TdeadbandC": AC_TdeadbandC,
        "AC_TinitC": AC_TinitC,
        "HEAT_Tcontrol_GEC": HEAT_Tcontrol_GEC,
        "HEAT_Tcontrol_GEdeadbandC": HEAT_Tcontrol_GEdeadbandC,
        "HEAT_Tcontrol_CPC": HEAT_Tcontrol_CPC,
        "HEAT_Tcontrol_CPdeadbandC": HEAT_Tcontrol_CPdeadbandC,
        "HEAT_Tcontrol_SHEDC": HEAT_Tcontrol_SHEDC,
        "HEAT_Tcontrol_deadbandC": HEAT_Tcontrol_deadbandC,
        "HEAT_Tcontrol_ALUC": HEAT_Tcontrol_ALUC,
        "HEAT_Tcontrol_ALUdeadbandC": HEAT_Tcontrol_ALUdeadbandC,
        "HEAT_Tcontrol_LOADC": HEAT_Tcontrol_LOADC,
        "HEAT_Tcontrol_LOADdeadbandC": HEAT_Tcontrol_LOADdeadbandC,
        "HEAT_TbaselineC": HEAT_TbaselineC,
        "HEAT_TdeadbandC": HEAT_TdeadbandC,
        "HEAT_TinitC": HEAT_TinitC,
        "REG_TYPE": REG_TYPE,
        "REG_SIGNAL": REG_SIGNAL,
        "MIN_HOLD_STEPS": MIN_HOLD_STEPS,
        "MIN_HOLD_MINUTES": MIN_HOLD_MINUTES,
        "CONTROL_INTERVAL_STEPS": CONTROL_INTERVAL_STEPS,
        "ACTIVE_POWER_THRESHOLD_KW": ACTIVE_POWER_THRESHOLD_KW,
        "EXPECTED_ON_POWER_KW": EXPECTED_ON_POWER_KW,
        "FEEDBACK_GAIN": FEEDBACK_GAIN,
        "TRACKING_DEADBAND_KW": TRACKING_DEADBAND_KW,
        "MAX_RESPONSE_CHANGE_KW_PER_INTERVAL": MAX_RESPONSE_CHANGE_KW_PER_INTERVAL,
        "RELIABLE_CAPACITY_QUANTILE": RELIABLE_CAPACITY_QUANTILE,
        "MIN_INITIALIZED_HOMES": MIN_INITIALIZED_HOMES,
        "REG_DIR": REG_DIR,
        "REG_ADDRESS": REG_ADDRESS,
    }


def shift_time(time_str, minutes):
    """Helper function to add minutes to an 'HH:MM' string."""
    delta_t = dt.datetime.strptime(time_str, '%H:%M')
    new_delta_t = delta_t + dt.timedelta(minutes=minutes)
    return new_delta_t.strftime('%H:%M')


# def create_home_schedule(base_sched, bins, home_idx):
#     """
#     Calculates staggered start/end timedeltas for a specific home 
#     distributed across the defined ramp-in and ramp-out periods.
#     """
#     bin_idx = home_idx % bins

#     # Calculate the fraction of the ramp duration this bin represents.
#     # We use (bins - 1) so that the first bin is at the exact start (0.0), 
#     # and the last bin is at the exact end (1.0) of the ramp period.
#     ramp_fraction = (bin_idx / (bins - 1)) if bins > 1 else 0

#     def parse_time(time_str):
#         t = dt.datetime.strptime(time_str, '%H:%M')
#         return pd.Timedelta(hours=t.hour, minutes=t.minute)

#     home_schedule = {}

#     # Process all combinations of Time-of-Day (M/E) and Modes
#     times_of_day = ['M', 'E']
#     modes = ['ALU', 'LU', 'S', 'CP', 'GE']

#     for tod in times_of_day:
#         for mode in modes:
#             prefix = f"{tod}_{mode}" # e.g. "M_ALU"

#             # --- RAMP IN (Start of command) ---
#             rin_start_str = base_sched.get(f"{prefix}_rampin_start", "00:00")
#             rin_end_str = base_sched.get(f"{prefix}_rampin_end", rin_start_str)

#             rin_start_td = parse_time(rin_start_str)
#             rin_end_td = parse_time(rin_end_str)
#             rin_duration = rin_end_td - rin_start_td

#             # Interpolate ramp-in time based on bin position
#             home_start_td = rin_start_td + (rin_duration * ramp_fraction)

#             # --- RAMP OUT (End of command) ---
#             rout_start_str = base_sched.get(f"{prefix}_rampout_start", "00:00")
#             rout_end_str = base_sched.get(f"{prefix}_rampout_end", rout_start_str)

#             rout_start_td = parse_time(rout_start_str)
#             rout_end_td = parse_time(rout_end_str)
#             rout_duration = rout_end_td - rout_start_td

#             # Interpolate ramp-out time based on bin position
#             home_end_td = rout_start_td + (rout_duration * ramp_fraction)

#             home_schedule[prefix] = (home_start_td, home_end_td)

#     # print(home_idx)
#     # print(bin_idx)
#     # print(home_schedule)
#     return home_schedule


def f_to_c(temp_f): 
    return (temp_f - 32) * 5/9


def f_to_c_DB(temp_f):
    return 5/9 * temp_f



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
        for battery in root.findall('.//Vehicle/VehicleType/BatteryElectricVehicle/Battery'):
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


def build_equip(home_path, config):
    """Return fresh OCHRE equipment overrides and home-specific EV information.

    OFF skips overrides; it does not remove equipment from the home's HPXML.
    HVAC and dryer equipment continue to come from HPXML, as in EnergySched.
    """
    equipment = {}
    hpxml_file = os.path.join(home_path, config["XML_ADDRESS"])
    home_info = {"home_charger_kw": None, "home_ev_capacity": None}
    if config["WH_SIMULATION"] == "ON":
        equipment["Water Heating"] = {
            "Initial Temperature (C)": config["WH_TinitC"],
            "hp_only_mode": True,
            "Max Tank Temperature (C)": 70,
            "Upper Node": 3,
            "Lower Node": 10,
            "Upper Node Weight": 0.75,
        }
    if config["BATTERY_SIMULATION"] == "ON":
        equipment["Battery"] = copy.deepcopy(config["BATTERY_PARAMS"])
    if config["EV_SIMULATION"] == "ON":
        charger_kw = get_ev_charger_power(hpxml_file, config["DEFAULT_CHARGER_POWER_KW"])
        capacity_kwh = get_ev_capacity_or_range(hpxml_file, config["DEFAULT_CAPACITY_KWH"])
        home_info.update(home_charger_kw=charger_kw, home_ev_capacity=capacity_kwh)
        equipment["EV"] = {
            "vehicle_type": "BEV",
            "capacity": capacity_kwh,
            "charging_level": "Level 2" if charger_kw > 10 else "Level 1",
            "max_power": charger_kw,
        }
    return equipment, home_info


# def build_norm_cntrl(config, home_info, sim_time=None):
#     """Return a fresh normal-control dictionary matching the old baseline.

#     sim_time is reserved for a future time-dependent normal policy. Dryer and
#     battery commands are omitted, preserving their existing baseline behavior.
#     B2 must explicitly release any overrides on those devices when appropriate.
#     """
#     control = {}
#     for flag, end_use, prefix in (
#         ("WH_SIMULATION", "Water Heating", "WH"),
#         ("HVAC_SIMULATION", "HVAC Cooling", "AC"),
#         ("HVAC_SIMULATION", "HVAC Heating", "HEAT"),
#     ):
#         if config[flag] == "ON":
#             control[end_use] = {
#                 "Setpoint": config[prefix + "_TbaselineC"],
#                 "Deadband": config[prefix + "_TdeadbandC"],
#                 "Load Fraction": 1,
#             }
#     if config["EV_SIMULATION"] == "ON" and home_info["home_charger_kw"] is not None:
#         control["EV"] = {"Max Power": home_info["home_charger_kw"]}
#     return control


def init_home(home_path, config, schedule_file, run_kind="baseline"):
    """Construct one independent dwelling; return (dwelling, home_info).

    Call separately for B1 and B2 with matching config and prepared schedules.
    Does not prepare/overwrite schedules, advance time, or finalize results.
    Initialization resets global random generators: call serially or in separate
    processes, not concurrently in threads, to preserve the existing seeding.
    """
    if run_kind not in {"baseline", "controlled"}:
        raise ValueError("run_kind must be 'baseline' or 'controlled'")
    equipment, home_info = build_equip(home_path, config)
    home_name = os.path.basename(os.path.normpath(home_path))
    digits = re.sub(r"\D", "", home_name)
    home_seed = int(digits) if digits else 0
    random.seed(home_seed)
    np.random.seed(home_seed)
    dwelling = Dwelling(
        name=f"{run_kind}_{home_name}",
        start_time=config["Start"],
        time_res=dt.timedelta(minutes=config["t_res"]),
        duration=dt.timedelta(days=config["Duration"]),
        hpxml_file=os.path.join(home_path, config["XML_ADDRESS"]),
        hpxml_schedule_file=os.fspath(schedule_file),
        initialization_time=dt.timedelta(days=1),
        weather_file=config["WEATHER_FILE"],
        verbosity=7,
        seed=home_seed,
        Equipment=equipment,
    )
    end_uses = sorted({eq.end_use for eq in dwelling.equipment.values() if eq.is_electric})
    participating = [end_use for end_use in end_uses if end_use in FLEX_END_USES
                     and config[FLEX_END_USES[end_use][1]] == "ON"]
    home_info.update(home_name=home_name, home_seed=home_seed,
                     present_end_uses=end_uses, participating_end_uses=participating,
                     response_delays_seconds=response_delays(home_seed, config))
    return dwelling, home_info


def format_results(df, config):
    """Return reporting columns with Time restored; never trim days or write files.

    Keep raw results separately when regulation needs temperatures or other state
    columns beyond this reporting schema. Missing optional device columns are
    skipped, matching EnergySched's export behavior.
    """
    result = df.copy()
    if "Time" not in result.columns:
        if not isinstance(result.index, pd.DatetimeIndex):
            raise ValueError("Results require a Time column or a DatetimeIndex")
        result.index.name = "Time"
        result = result.reset_index()
    result["Time"] = pd.to_datetime(result["Time"], errors="raise")
    if result["Time"].isna().any():
        raise ValueError("Results contain missing timestamps")
    columns = ["Time", "Total Electric Power (kW)", "Total Electric Energy (kWh)"]
    device_columns = {
        "WH_SIMULATION": ["Water Heating Electric Power (kW)"],
        "HVAC_SIMULATION": ["HVAC Heating Electric Power (kW)", "HVAC Cooling Electric Power (kW)"],
        "DRYER_SIMULATION": ["Clothes Dryer Electric Power (kW)"],
        "EV_SIMULATION": ["EV Electric Power (kW)", "EV SOC (-)"],
        "BATTERY_SIMULATION": ["Battery Electric Power (kW)", "Battery SOC (-)"],
    }
    for flag, names in device_columns.items():
        if config[flag] == "ON":
            columns.extend(names)
    return result[[name for name in columns if name in result.columns]].copy()



def signal_aggregator_mean(REG_DIR, REG_ADDRESS, REG_TYPE, Start, Duration, t_res, reg_signal=None):
    if reg_signal is None:
        reg_signal = pd.read_csv(os.path.join(REG_DIR, REG_ADDRESS))
    # assume sig_step in seconds and t_res in minutes
    reg_signal["timestamp"] = pd.to_datetime(reg_signal["Time"])

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

    save_sig(working_sig, REG_DIR, REG_TYPE)

    return working_sig


def save_sig(reg_sig, REG_DIR, REG_TYPE):

    saved_sig = pd.DataFrame({
        "Timestamp": reg_sig.index,
        "Signal": reg_sig.values
    })

    os.makedirs(REG_DIR, exist_ok=True)

    saved_sig.to_csv(
        os.path.join(REG_DIR, f"{REG_TYPE}_filtered.csv"),
        index=False
    )

    # print("Filtered regulation signal saved.")


REG_SIGNAL = pd.Series(dtype=float)


def configure_regulation(reg_type, REG_DIR, Start, Duration, t_res):
    """Select and load the regulation signal used by this B2 run."""
    # global REG_TYPE, REG_ADDRESS, REG_SIGNAL

    normalized_types = {"rega": "RegA", "regd": "RegD"}
    try:
        selected_type = normalized_types[str(reg_type).strip().lower()]
    except KeyError as exc:
        raise ValueError(
            f"reg_type must be 'RegA' or 'RegD'; received {reg_type!r}."
        ) from exc

    signal_file = os.path.join(REG_DIR, f"{selected_type}-ochre.csv")
    if not os.path.isfile(signal_file):
        raise FileNotFoundError(f"Regulation signal file not found: {signal_file}")

    REG_TYPE = selected_type
    REG_ADDRESS = f"{REG_TYPE}-ochre.csv"
    REG_SIGNAL = signal_aggregator_mean(REG_DIR, REG_ADDRESS, REG_TYPE, Start, Duration, t_res)


    # import numpy as np
    # duration_min = Duration * 24 * 60
    # frequency = f"{t_res}min"
    # period = int(duration_min / t_res)
    # sim_times = pd.date_range(start=Start, periods=period, freq=frequency)
    # x = np.arange(0, 1440*0.1, 0.1)
    # REG_SIGNAL = pd.Series(
    #     np.sin(x),
    #     index=sim_times
    # )
    return REG_SIGNAL
