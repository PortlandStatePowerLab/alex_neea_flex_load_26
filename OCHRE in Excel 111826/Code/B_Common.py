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
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
import warnings
from types import MethodType
from ochre.Equipment.EV import EV_EFFICIENCY, ElectricVehicle
from ochre.Equipment.EventBasedLoad import EventBasedLoad
from ochre.Equipment.HVAC import ASHPHeater, ASHPCooler
from ochre.Models.Envelope import rho_air, cp_air
from ochre.utils import load_hpxml


class CalculatorEV(ElectricVehicle):
    def __init__(self, charging_efficiency=EV_EFFICIENCY, usable_flexibility=1.0, **kwargs):
        self.charging_efficiency = charging_efficiency
        self.usable_flexibility = usable_flexibility
        super().__init__(**kwargs)

    def charging_floor_kw(self, sim_time, soc=None):
        if not self.in_event:
            return 0.0
        event = self.all_events.loc[self.event_index]
        elapsed = min(sim_time + self.time_res, self.event_end) - self.event_start
        hours = self.time_res.total_seconds() / 3600
        baseline_soc = min(1, event["start_soc"] + self.max_power * self.charging_efficiency
                           * elapsed.total_seconds() / 3600 / self.capacity)
        minimum_soc = baseline_soc - self.usable_flexibility
        available_soc = self.soc if soc is None else soc
        return max(0, minimum_soc - available_soc) * self.capacity / hours / self.charging_efficiency

    def initialize_schedule(self, **kwargs):
        schedule = super().initialize_schedule(**kwargs)
        hours = self.all_events["duration"].dt.total_seconds() / 3600
        self.all_events["end_soc"] = (
            self.all_events["start_soc"]
            + self.max_power * self.charging_efficiency * hours / self.capacity
        ).clip(upper=1)
        return schedule

    def end_event(self):
        super().end_event()
        event = self.all_events.loc[self.event_index]
        hours = event["duration"].total_seconds() / 3600
        self.all_events.loc[self.event_index, "end_soc"] = min(
            1, event["start_soc"] + self.max_power * self.charging_efficiency * hours / self.capacity
        )

    def calculate_power_and_heat(self):
        if self.mode == "Off":
            return super().calculate_power_and_heat()
        hours = self.time_res.total_seconds() / 3600
        room_kw = max(0, self.soc_max_ctrl - self.soc) * self.capacity / hours
        requested_kw = max(self.p_setpoint, self.charging_floor_kw(self.current_time))
        self.electric_kw = min(requested_kw, self.max_power, room_kw / self.charging_efficiency)
        battery_kw = self.electric_kw * self.charging_efficiency
        self.next_soc = self.soc + battery_kw * hours / self.capacity
        self.sensible_gain = self.electric_kw - battery_kw

    def make_equivalent_battery_model(self):
        result = super().make_equivalent_battery_model()
        result[f"{self.end_use} EBM Efficiency (-)"] = self.charging_efficiency
        return result


class CalculatorHVAC:
    """Apply calculator ratings after OCHRE resolves the HPXML equipment."""

    def __init__(self, calculator_rated_power=None, calculator_minimum_modulation=None, **kwargs):
        capacities = np.atleast_1d(kwargs["Capacity (W)"])
        if calculator_rated_power is not None:
            compressor_w = calculator_rated_power - kwargs["Rated Auxiliary Power (W)"]
            if compressor_w <= 0:
                raise ValueError("Rated HVAC electrical power must exceed rated fan power")
            original_eir = np.atleast_1d(kwargs["EIR (-)"])
            scaled_eir = original_eir * (compressor_w / (capacities[-1] * original_eir[-1]))
            kwargs["EIR (-)"] = scaled_eir.tolist() if len(scaled_eir) > 1 else float(scaled_eir[0])
        if calculator_minimum_modulation is not None:
            kwargs["use_ideal_capacity"] = True
            kwargs["Minimum Capacity (W)"] = capacities[-1] * calculator_minimum_modulation
        super().__init__(**kwargs)


class CalculatorHeater(CalculatorHVAC, ASHPHeater):
    pass


class CalculatorCooler(CalculatorHVAC, ASHPCooler):
    pass


class CalculatorDryer(EventBasedLoad):
    end_use = "Clothes Dryer"

    def __init__(self, calculator_max_deferral=0, **kwargs):
        self.max_deferral = dt.timedelta(minutes=calculator_max_deferral)
        super().__init__(**kwargs)

    def can_defer(self, sim_time, *, baseline_sample=False):
        if (self.in_event and not baseline_sample) or self.event_start != sim_time:
            return False
        original_start = self.all_events.loc[self.event_index, "start_time"]
        if self.event_start + self.time_res > original_start + self.max_deferral:
            return False
        if self.event_index + 1 < len(self.all_events):
            next_start = self.all_events.loc[self.event_index + 1, "start_time"]
            if self.event_end + self.time_res > next_start:
                return False
        return self.event_end > self.event_start

    def extract_events(self, eq_powers, **kwargs):
        events = super().extract_events(eq_powers, **kwargs)
        duration = kwargs.get("calculator_cycle_duration")
        energy = kwargs.get("calculator_cycle_energy")
        rating = kwargs.get("calculator_rated_power")
        if events.empty:
            return events
        if duration is not None:
            duration = max(self.time_res, pd.Timedelta(minutes=duration).round(self.time_res))
            # Preserve scheduled starts when possible, and serialize overlapping cycles.
            end = events["start_time"].iloc[0]
            for index, start in events["start_time"].items():
                start = max(start, end)
                end = start + duration
                events.loc[index, ["start_time", "end_time"]] = [start, end]
        if energy is not None:
            hours = (events["end_time"] - events["start_time"]).dt.total_seconds() / 3600
            events["power"] = energy / hours
            if rating is not None and (events["power"] > rating + 1e-9).any():
                raise ValueError("Dryer cycle energy and duration require power above its rating")
        elif rating is not None:
            events["power"] = rating
        return events


def ev_charging_floor_kw(ev, sim_time, *, baseline_sample=False):
    if hasattr(ev, "charging_floor_kw") and sim_time is not None:
        soc = ev.soc
        if baseline_sample:
            # OCHRE advances SOC before B1 reads the completed timestep.
            hours = ev.time_res.total_seconds() / 3600
            soc -= ev.electric_kw * ev.charging_efficiency * hours / ev.capacity
        return ev.charging_floor_kw(sim_time, soc)
    return 0.0


def hvac_regulation_limits(temperature, heating, settings):
    """Return eligibility for load-up and shed at the indoor comfort limits."""
    lower = settings.get("HVAC_MIN_TEMPERATURE_C", -np.inf)
    upper = settings.get("HVAC_MAX_TEMPERATURE_C", np.inf)
    return (temperature < upper, temperature > lower) if heating else (
        temperature > lower, temperature < upper
    )


def _ev_generate_results(ev):
    """Handle paused charging in OCHRE's verbosity-7 charge-time diagnostic."""
    if ev.verbosity < 7 or (ev.max_power_ctrl != 0 and not isinstance(ev, CalculatorEV)):
        return ElectricVehicle.generate_results(ev)
    # Skip only the upstream diagnostic that divides by the zero power limit.
    # Restore verbosity even on failure; physical charging controls stay intact.
    verbosity = ev.verbosity
    try:
        ev.verbosity = 6
        results = ElectricVehicle.generate_results(ev)
    finally:
        ev.verbosity = verbosity
    results[f"{ev.end_use} Start Time"] = ev.event_start
    results[f"{ev.end_use} End Time"] = ev.event_end
    results[f"{ev.end_use} Remaining Charge Time (min)"] = (
        0.0 if ev.soc >= 1 else
        (1 - ev.soc) * ev.capacity / (ev.max_power_ctrl * ev.charging_efficiency) * 60
        if ev.max_power_ctrl else float("inf")
    )
    return results


def numerical_threads(config):
    """Limit BLAS threads for small OCHRE matrices; restore on leaving the run."""
    threads = config.get("NUMERICAL_THREADS", 1)
    if isinstance(threads, bool) or not isinstance(threads, int) or threads < 1:
        raise ValueError("NUMERICAL_THREADS must be a positive integer")
    try:
        from threadpoolctl import threadpool_limits
    except ImportError:
        warnings.warn("Install threadpoolctl to prevent nested BLAS thread contention", RuntimeWarning)
        return nullcontext()
    return threadpool_limits(limits=threads, user_api="blas")


def fleet_executor(config):
    """Avoid creating millions of Futures when serial stepping is selected."""
    workers = config.get("FLEET_WORKERS", 1)
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise ValueError("FLEET_WORKERS must be a positive integer")
    return nullcontext(None) if workers == 1 else ThreadPoolExecutor(max_workers=workers)


def step_fleet(executor, worker, fleet, sim_time):
    if executor is None:
        return [worker(home, sim_time) for home in fleet]
    from itertools import repeat
    return list(executor.map(worker, fleet, repeat(sim_time)))


def aggregate_home_results(homes, work_dir, expected_times, required_by_home,
                           kind, validate):
    """Write the column union one home at a time instead of holding the fleet."""
    if not homes:
        raise ValueError("Cannot aggregate an empty fleet")
    sources = []
    columns = []
    for home in homes:
        name = Path(home).name
        source = Path(work_dir) / "homes" / name / f"home_{kind}.csv"
        if not source.is_file():
            raise FileNotFoundError(source)
        sources.append((name, source))
        for column in [*pd.read_csv(source, nrows=0).columns, "Home"]:
            if column not in columns:
                columns.append(column)
    output = Path(work_dir) / f"{kind}.csv"
    with output.open("w", encoding="utf-8", newline="") as stream:
        for index, (name, source) in enumerate(sources):
            frame = validate(pd.read_csv(source), expected_times, name, required_by_home[name])
            frame["Home"] = name
            frame.reindex(columns=columns).to_csv(stream, index=False, header=index == 0)
    return str(output)

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

    selected_device = config.get("DEVICE_TYPE")
    response_s = config.get("DEVICE_RESPONSE_TIME_S")

    if selected_device is not None and response_s is not None:
        command_device = {
            "HPWH": "WH",
            "ERWH": "WH",
            "HVAC": "HVAC",
            "EV": "EV",
            "Dryer": "Dryer",
            "Battery": "Battery",
        }[selected_device]

        delays[command_device] = response_s
    
    return delays


def load_configuration(Season, Weekday, Output_Folder):
    #########################################
    # USER SETTINGS
    #########################################

    filename = 'Combo_WH_HVAC_Dryer_EV_Battery_TEST_3'

    Input_folder = "Combo Regulation All Input Files"

    # Original OCHRE defaults folder
    ochre_dir = Path(ochre.__file__).resolve().parent
    DEFAULT_INPUT = ochre_dir / "defaults" / "Input Files"
    # print("OCHRE installed at:", ochre_dir)
    # print(DEFAULT_INPUT)

    DEFAULT_WEATHER = ochre_dir / "defaults" / "Weather" / "USA_OR_Portland.Intl.AP.726980_TMY3.epw"
    # G4100510 is Multnomah county weather station, code will complain this is missing but it doesn't work if you actually try to use it

    # working folder
    script_dir = os.path.dirname(os.path.abspath(__file__))
    fl_dir = str(Path(script_dir).parent.parent)
    WORKING_DIR = os.path.dirname(fl_dir)
    INPUT_DIR = os.path.join(fl_dir, Input_folder, "bldg")
    WEATHER_DIR = os.path.join(fl_dir, "Weather")
    WEATHER_FILE = os.path.join(WEATHER_DIR, "USA_OR_Portland.Intl.AP.726980_TMY3.epw")
    XML_ADDRESS = "home.xml"
    CSV_ADDRESS = "in.schedules.csv"

    # Simulation parameters
    # Choose the warm-up date so day two matches the requested day type.
    season_dates = {
        "Spring": (4, 11, 14),
        "Summer": (7, 18, 21),
        "Fall": (10, 17, 20),
        "Winter": (1, 17, 20),
    }
    if Season not in season_dates:
        raise ValueError("Season must be Spring, Summer, Fall, or Winter.")
    month, weekday_start, weekend_start = season_dates[Season]
    # A Saturday warm-up keeps day two on a weekend.
    Start = dt.datetime(2018, month, weekday_start if Weekday else weekend_start)
    Duration = 2  # days
    t_res = 1  # minutes

    # NUM_HOMES = 10

    # B3 receives its directional regulation capacities from B2's baseline run.

    # Controller hold; physical OCHRE cycling limits remain enforced.
    MIN_HOLD_MINUTES = 1
    MIN_HOLD_STEPS = max(1, round(MIN_HOLD_MINUTES / t_res))
    CONTROL_INTERVAL_MINUTES = 1
    CONTROL_INTERVAL_STEPS = max(1, round(CONTROL_INTERVAL_MINUTES / t_res))
    ACTIVE_POWER_THRESHOLD_KW = 0.1
    EXPECTED_ON_POWER_KW = 0.5
    # Partial corrections reduce hunting when thermal response estimates and
    # delayed activations differ from the power delivered next minute.
    # Set to 1.0 to reproduce the previous full-error correction.
    FEEDBACK_GAIN = 0.8
    TRACKING_DEADBAND_KW = 0.25
    # None lets B2 use the full directional capacity span. A fixed 10 kW
    # fleet-wide limit prevented large fleets from following fast signals.
    # Set a finite nonnegative kW value to study an explicit dispatch limit.
    MAX_RESPONSE_CHANGE_KW_PER_INTERVAL = None

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
        "REG_SIGNAL": REG_SIGNAL,
        "MIN_HOLD_STEPS": MIN_HOLD_STEPS,
        "MIN_HOLD_MINUTES": MIN_HOLD_MINUTES,
        "CONTROL_INTERVAL_STEPS": CONTROL_INTERVAL_STEPS,
        "ACTIVE_POWER_THRESHOLD_KW": ACTIVE_POWER_THRESHOLD_KW,
        "EXPECTED_ON_POWER_KW": EXPECTED_ON_POWER_KW,
        "FEEDBACK_GAIN": FEEDBACK_GAIN,
        "REGULATION_CAPACITY_FRACTION": 1.0,
        "REGULATION_CAPACITY_MODE": "asymmetric",
        "ENERGY_AWARE_DISPATCH": True,
        "ENERGY_RECOVERY_HOURS": 2.0,
        "CONTINUOUS_POWER_CONTROL": True,
        "CAUSAL_LOOKAHEAD": True,
        "TRACKING_DEADBAND_KW": TRACKING_DEADBAND_KW,
        "MAX_RESPONSE_CHANGE_KW_PER_INTERVAL": MAX_RESPONSE_CHANGE_KW_PER_INTERVAL,
        "RELIABLE_CAPACITY_QUANTILE": RELIABLE_CAPACITY_QUANTILE,
        "MIN_INITIALIZED_HOMES": MIN_INITIALIZED_HOMES,
        # Runtime settings do not change the physical model or control cadence.
        "FLEET_WORKERS": 2,
        "NUMERICAL_THREADS": 1,
        "OUTPUT_FOLDER": Output_Folder,
        "RESULTS_DIR": str(Path(__file__).resolve().parent.parent / Output_Folder),
    }


def load_configuration_hardcoded():
    #########################################
    # USER SETTINGS
    #########################################

    filename = 'Combo_WH_HVAC_Dryer_EV_Battery_TEST_3'

    Input_folder = "Combo Regulation All Input Files"

    # Original OCHRE defaults folder
    ochre_dir = Path(ochre.__file__).resolve().parent
    DEFAULT_INPUT = ochre_dir / "defaults" / "Input Files"
    # print("OCHRE installed at:", ochre_dir)
    # print(DEFAULT_INPUT)

    DEFAULT_WEATHER = ochre_dir / "defaults" / "Weather" / "USA_OR_Portland.Intl.AP.726980_TMY3.epw"
    # G4100510 is Multnomah county weather station, code will complain this is missing but it doesn't work if you actually try to use it

    # working folder
    script_dir = os.path.dirname(os.path.abspath(__file__))
    fl_dir = str(Path(script_dir).parent.parent)
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
    Duration = 2  # days
    t_res = 1  # minutes

    # NUM_HOMES = 10

    # B3 receives its directional regulation capacities from B2's baseline run.

    # Controller hold; physical OCHRE cycling limits remain enforced.
    MIN_HOLD_MINUTES = 1
    MIN_HOLD_STEPS = max(1, round(MIN_HOLD_MINUTES / t_res))
    CONTROL_INTERVAL_MINUTES = 1
    CONTROL_INTERVAL_STEPS = max(1, round(CONTROL_INTERVAL_MINUTES / t_res))
    ACTIVE_POWER_THRESHOLD_KW = 0.1
    EXPECTED_ON_POWER_KW = 0.5
    # Partial corrections reduce hunting when thermal response estimates and
    # delayed activations differ from the power delivered next minute.
    # Set to 1.0 to reproduce the previous full-error correction.
    FEEDBACK_GAIN = 0.8
    TRACKING_DEADBAND_KW = 0.25
    # None lets B2 use the full directional capacity span. A fixed 10 kW
    # fleet-wide limit prevented large fleets from following fast signals.
    # Set a finite nonnegative kW value to study an explicit dispatch limit.
    MAX_RESPONSE_CHANGE_KW_PER_INTERVAL = None

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
        "REGULATION_CAPACITY_FRACTION": 1.0,
        "REGULATION_CAPACITY_MODE": "asymmetric",
        "ENERGY_AWARE_DISPATCH": True,
        "ENERGY_RECOVERY_HOURS": 2.0,
        "CONTINUOUS_POWER_CONTROL": True,
        "CAUSAL_LOOKAHEAD": True,
        "TRACKING_DEADBAND_KW": TRACKING_DEADBAND_KW,
        "MAX_RESPONSE_CHANGE_KW_PER_INTERVAL": MAX_RESPONSE_CHANGE_KW_PER_INTERVAL,
        "RELIABLE_CAPACITY_QUANTILE": RELIABLE_CAPACITY_QUANTILE,
        "MIN_INITIALIZED_HOMES": MIN_INITIALIZED_HOMES,
        # Runtime settings do not change the physical model or control cadence.
        "FLEET_WORKERS": 8,
        "NUMERICAL_THREADS": 2,
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


def estimate_wh_regulation_capacity_kw(home, wh, settings):
    """Estimate immediate LU/S headroom without advancing the equipment.

    Uses current temperatures and current capacity/COP. This estimates
    instantaneous response, not sustained capacity or delayed response.
    """
    if not wh.is_electric or wh.is_gas:
        return 0.0, 0.0

    if wh.use_ideal_capacity:
        raise ValueError(
            "WH response estimation currently requires "
            "thermostat control, not ideal-capacity control"
        )

    measured_kw = float(wh.electric_kw)
    temperatures = np.asarray(wh.model.states, dtype=float)

    if (
        not np.isfinite(measured_kw)
        or temperatures.ndim != 1
        or not temperatures.size
        or not np.isfinite(temperatures).all()
    ):
        raise ValueError("Invalid water-heater power or temperatures")

    measured_kw = max(0.0, measured_kw)

    def predicted_power(setpoint, deadband):
        # The copy shares temperature data, which the thermostat only reads.
        # Changes to mode/setpoint/deadband affect the copy, not the real WH.
        probe = copy.copy(wh)
        probe.setpoint_temp = float(setpoint)
        probe.deadband_temp = float(deadband)

        requested_mode = probe.run_thermostat_control()

        # None means retain the current physical mode.
        if requested_mode is None:
            requested_mode = wh.mode

        # Match OCHRE's minimum-time restriction.
        minimum_time = wh.min_time_in_mode.get(wh.mode)
        if (
            requested_mode != wh.mode
            and minimum_time is not None
            and wh.time_in_mode < minimum_time
        ):
            requested_mode = wh.mode

        if requested_mode == "Heat Pump On":
            power_kw = (
                wh.hp_capacity / wh.hp_cop
                + wh.fan_power
            ) / 1000.0

        elif requested_mode in {"Upper On", "Lower On"}:
            power_kw = wh.capacity_rated / wh.efficiency / 1000.0

            # HPWH electronics remain powered when resistance heat runs.
            if hasattr(wh, "hp_capacity"):
                power_kw += wh.parasitic_power / 1000.0

        elif requested_mode == "Off":
            power_kw = (
                getattr(wh, "parasitic_power", 0.0) / 1000.0
            )

        else:
            raise ValueError(
                f"Unsupported water-heater mode: {requested_mode!r}"
            )

        if not np.isfinite(power_kw) or power_kw < 0:
            raise ValueError("Invalid predicted water-heater power")

        return power_kw

    load_power = predicted_power(
        settings["WH_Tcontrol_LOADC"],
        settings["WH_Tcontrol_LOADdeadbandC"],
    )

    shed_power = predicted_power(
        settings["WH_Tcontrol_SHEDC"],
        settings["WH_Tcontrol_deadbandC"],
    )

    up_kw = max(0.0, load_power - measured_kw)
    down_kw = max(0.0, measured_kw - shed_power)

    # Apply the study's service-temperature limits to both B1 and B2.
    maximum = settings.get("WH_MAX_TEMPERATURE_C")
    minimum = settings.get("WH_MIN_TEMPERATURE_C")
    margin = float(settings.get("WH_LIMIT_MARGIN_C", 0.0))

    if maximum is not None:
        if temperatures.max() >= float(maximum) - margin:
            up_kw = 0.0

    if minimum is not None:
        service_index = settings["WH_SERVICE_NODE_INDEX"]
        if not 0 <= service_index < len(temperatures):
            raise ValueError("Invalid WH service-node index")

        if temperatures[service_index] <= float(minimum) + margin:
            down_kw = 0.0

    return up_kw, down_kw

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
            "Max Tank Temperature (C)": config.get(
                "WH_MAX_TEMPERATURE_C", 70
            ),
            "Upper Node": 3,
            "Lower Node": 10,
            "Upper Node Weight": 0.75,
        }
        if config.get("DEVICE_TYPE") == "HPWH":
            physical = config["DEVICE_PARAMETERS"].get("physical", {})
            efficiency = physical.get("rated_efficiency")
            if efficiency is not None:
                if efficiency.get("type") != "COP":
                    raise ValueError("HPWH rated_efficiency type must be COP")
                cop_value = efficiency.get("value")
                if isinstance(cop_value, bool):
                    raise ValueError("HPWH COP must be finite and positive")
                cop = float(cop_value)
                if not np.isfinite(cop) or cop <= 0:
                    raise ValueError("HPWH COP must be finite and positive")
                equipment["Water Heating"]["HPWH COP (-)"] = cop

            compressor_w = physical.get("rated_compressor_power_w")

            if compressor_w is not None:
                if isinstance(compressor_w, bool):
                    raise ValueError("Compressor power must be numeric")

                compressor_w = float(compressor_w)

                if not np.isfinite(compressor_w) or compressor_w <= 0:
                    raise ValueError(
                        "Compressor power must be finite and greater than zero"
                    )

                equipment["Water Heating"]["HPWH Power (W)"] = compressor_w
    if config["BATTERY_SIMULATION"] == "ON":
        equipment["Battery"] = copy.deepcopy(config["BATTERY_PARAMS"])
    if config["EV_SIMULATION"] == "ON":
        charger_kw = get_ev_charger_power(hpxml_file, config["DEFAULT_CHARGER_POWER_KW"])
        capacity_kwh = get_ev_capacity_or_range(hpxml_file, config["DEFAULT_CAPACITY_KWH"])
        home_info.update(home_charger_kw=charger_kw, home_ev_capacity=capacity_kwh)
        capacity_kwh = config.get("EV_BATTERY_CAPACITY_KWH", capacity_kwh)
        home_info["home_ev_capacity"] = capacity_kwh
        equipment["EV"] = {
            "vehicle_type": "BEV",
            "capacity": capacity_kwh,
            "charging_level": "Level 2" if charger_kw > 10 else "Level 1",
            "max_power": charger_kw,
        }
        if "EV_CHARGING_EFFICIENCY" in config or "EV_FLEXIBILITY" in config:
            equipment["EV"].update(equipment_class=CalculatorEV,
                                   charging_efficiency=config.get("EV_CHARGING_EFFICIENCY", EV_EFFICIENCY),
                                   usable_flexibility=config.get("EV_FLEXIBILITY", 1.0))
    if config.get("DEVICE_TYPE") == "HVAC":
        power = config.get("HVAC_RATED_POWER_W")
        modulation = config.get("HVAC_MINIMUM_MODULATION")
        if power is not None or modulation is not None:
            for cls, original in ((CalculatorHeater, ASHPHeater), (CalculatorCooler, ASHPCooler)):
                equipment[original.name] = dict(equipment_class=cls,
                                               calculator_rated_power=power,
                                               calculator_minimum_modulation=modulation)
    if config.get("DEVICE_TYPE") == "Dryer":
        dryer_options = {
            "calculator_cycle_duration": config.get("DRYER_CYCLE_DURATION_MIN"),
            "calculator_cycle_energy": config.get("DRYER_CYCLE_ENERGY_KWH"),
            "calculator_rated_power": config.get("DRYER_RATED_POWER_KW"),
            "calculator_max_deferral": config.get("DRYER_MAX_DEFERRAL_MIN", 0),
        }
        equipment["Clothes Dryer"] = dict(equipment_class=CalculatorDryer, **dryer_options)
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
    xml_path = os.path.join(home_path, config["XML_ADDRESS"])
    envelope = {}
    if "HVAC_BUILDING_THERMAL_CAPACITY" in config:
        properties, _ = load_hpxml(hpxml_file=xml_path)
        zones = properties["zones"]
        volume = zones["Indoor"]["Volume (m^3)"]
        thermal_kj_per_c = config["HVAC_BUILDING_THERMAL_CAPACITY"] * 3600 * 1.8
        zones["Indoor"]["Thermal Mass Multiplier"] = thermal_kj_per_c / (volume * rho_air * cp_air)
        envelope["zones"] = zones
    dwelling = Dwelling(
        name=f"{run_kind}_{home_name}",
        start_time=config["Start"],
        time_res=dt.timedelta(minutes=config["t_res"]),
        duration=dt.timedelta(days=config["Duration"]),
        hpxml_file=xml_path,
        hpxml_schedule_file=os.fspath(schedule_file),
        weather_file=config["WEATHER_FILE"],
        verbosity=7,
        # Combo writes the validated per-home and aggregate exports itself.
        # Keep full diagnostics in memory without duplicate OCHRE CSV/JSON,
        # schedule and hourly exports in the input directories.
        save_results=False,
        save_status=False,
        seed=home_seed,
        Equipment=equipment,
        Envelope=envelope,
    )
    for eq in dwelling.equipment.values():
        if isinstance(eq, ElectricVehicle):
            eq.generate_results = MethodType(_ev_generate_results, eq)
    if config.get("DEVICE_TYPE") == "HPWH":
        hpwh = next(
            (
                eq for eq in dwelling.equipment.values()
                if eq.end_use == "Water Heating"
                and hasattr(eq, "hp_capacity_nominal")
            ),
            None,
        )

        if hpwh is None:
            raise ValueError(f"{home_name}: expected an HPWH")

        expected_power = config["DEVICE_PARAMETERS"]["physical"].get(
            "rated_compressor_power_w"
        )

        nominal_power = hpwh.hp_capacity_nominal / hpwh.cop_nominal

        if expected_power is not None and not np.isclose(
            nominal_power, float(expected_power)
        ):
            raise ValueError(
                f"{home_name}: requested {expected_power} W, "
                f"but initialized {nominal_power} W"
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


def configure_regulation(Start, Duration, t_res, sine_freq):
    """Generate the single sine regulation signal used by B2."""
    # Frequency is cycles per minute; sample at the actual simulation cadence.
    sine_freq = float(sine_freq)
    if not np.isfinite(sine_freq) or sine_freq <= 0:
        raise ValueError("sine_freq must be finite and positive (cycles per minute)")
    if not np.isfinite(t_res) or t_res <= 0:
        raise ValueError("t_res must be finite and positive")
    if sine_freq >= 0.5 / t_res:
        raise ValueError("sine_freq must be below the simulation Nyquist frequency")
    period = int(Duration * 24 * 60 / t_res)
    sim_times = pd.date_range(start=Start, periods=period,
                              freq=pd.Timedelta(minutes=t_res))
    elapsed_minutes = np.arange(period, dtype=float) * t_res
    REG_SIGNAL = pd.Series(np.sin(2 * np.pi * sine_freq * elapsed_minutes),
                           index=sim_times)
    return REG_SIGNAL


def apply_device_parameters(
    config,
    device_type,
    parameters,
    input_dir,
):
    settings = copy.deepcopy(config)

    device_flags = {
        "HPWH": "WH_SIMULATION",
        "ERWH": "WH_SIMULATION",
        "HVAC": "HVAC_SIMULATION",
        "EV": "EV_SIMULATION",
        "Dryer": "DRYER_SIMULATION",
        "Battery": "BATTERY_SIMULATION",
    }

    if device_type not in device_flags:
        raise ValueError(f"Unknown device type: {device_type}")

    if not isinstance(parameters, dict):
        raise TypeError("device_parameters must be a dictionary")

    for section in (
        "physical", "controller", "control", "interoperability"
    ):
        if not isinstance(parameters.get(section, {}), dict):
            raise TypeError(f"{section} must be a dictionary")

    settings["DEVICE_TYPE"] = device_type
    settings["DEVICE_PARAMETERS"] = copy.deepcopy(parameters)

    # Select which end use participates in the study.
    # OFF does not remove other equipment from the dwelling.
    for flag in set(device_flags.values()):
        settings[flag] = "OFF"

    settings[device_flags[device_type]] = "ON"

    # B_Common expects the directory containing building folders.
    prepared_dir = Path(input_dir)
    building_dir = prepared_dir / "bldg"

    if building_dir.is_dir():
        prepared_dir = building_dir

    if not prepared_dir.is_dir():
        raise FileNotFoundError(prepared_dir)

    settings["INPUT_DIR"] = str(prepared_dir.resolve())

    controller = parameters.get("controller", {})

    def numeric(key, minimum, allow_equal=True, fields=controller):
        value = fields.get(key)
        if value is None:
            return None

        if isinstance(value, bool):
            raise ValueError(f"{key} must be numeric")

        value = float(value)

        if not np.isfinite(value):
            raise ValueError(f"{key} must be finite")

        invalid = (
            value < minimum if allow_equal else value <= minimum
        )
        if invalid:
            raise ValueError(f"Invalid {key}: {value}")

        return value

    response_s = numeric("response_time_s", 0)
    if response_s is not None:
        settings["DEVICE_RESPONSE_TIME_S"] = response_s

    interval_s = numeric(
        "control_interval_s", 0, allow_equal=False
    )
    if interval_s is not None:
        timestep_s = float(settings["t_res"]) * 60.0

        # Round upward: never update faster than requested.
        settings["CONTROL_INTERVAL_STEPS"] = max(
            1, int(np.ceil(interval_s / timestep_s))
        )

        settings["EFFECTIVE_CONTROL_INTERVAL_S"] = (
            settings["CONTROL_INTERVAL_STEPS"] * timestep_s
        )

    if device_type == "Battery":
        physical = parameters.get("physical", {})
        battery = settings["BATTERY_PARAMS"]
        rated_power = numeric("rated_power_kw", 0, allow_equal=False, fields=physical)
        usable_energy = numeric("usable_energy_capacity_kwh", 0, allow_equal=False, fields=physical)
        recovery_rate = numeric("recovery_rate_kw", 0)
        soc_range = controller.get("soc_operating_range_pct")
        if soc_range is not None:
            if isinstance(soc_range, (list, tuple)):
                if len(soc_range) != 2 or any(isinstance(value, bool) for value in soc_range):
                    raise ValueError("Battery SOC range must have two percentage endpoints")
                low, high = map(float, soc_range)
            else:
                width = numeric("soc_operating_range_pct", 0, allow_equal=False)
                low, high = 50 - width / 2, 50 + width / 2
            if not 0 <= low < high <= 100:
                raise ValueError("Battery SOC range must satisfy 0 <= minimum < maximum <= 100")
            battery.update(soc_min=low / 100, soc_max=high / 100,
                           soc_init=(low + high) / 200)
        soc_span = battery["soc_max"] - battery["soc_min"]
        if usable_energy is not None:
            battery["capacity_kwh"] = usable_energy / soc_span
        if rated_power is not None:
            battery["capacity"] = rated_power
        rated_power = battery["capacity"]
        if recovery_rate is not None:
            if recovery_rate > rated_power:
                raise ValueError("Battery recovery rate cannot exceed rated power")
            settings["BATTERY_RECOVERY_RATE_KW"] = recovery_rate
        for mode, fraction in (
            ("ALU", 1.0), ("LU", 0.25), ("SHED", -0.25),
            ("CP", -0.5), ("GE", -1.0),
        ):
            settings[f"P_Battery_{mode}_KW"] = fraction * rated_power

    physical = parameters.get("physical", {})
    device_fields = {
        "HVAC": [
            ("rated_electrical_power_w", "HVAC_RATED_POWER_W", physical, 0, False, None),
            ("effective_building_thermal_capacity_kwh_per_f", "HVAC_BUILDING_THERMAL_CAPACITY", physical, 0, False, None),
            ("minimum_modulation_pct", "HVAC_MINIMUM_MODULATION", controller, 0, True, 100),
        ],
        "EV": [
            ("maximum_battery_capacity_kwh", "EV_BATTERY_CAPACITY_KWH", physical, 0, False, None),
            ("charging_efficiency_pct", "EV_CHARGING_EFFICIENCY", physical, 0, False, 100),
            ("usable_battery_flexibility_pct", "EV_FLEXIBILITY", controller, 0, True, 100),
        ],
        "Dryer": [
            ("rated_power_kw", "DRYER_RATED_POWER_KW", physical, 0, False, None),
            ("cycle_energy_kwh", "DRYER_CYCLE_ENERGY_KWH", physical, 0, False, None),
            ("typical_cycle_duration_min", "DRYER_CYCLE_DURATION_MIN", physical, 0, False, None),
            ("maximum_deferral_time_min", "DRYER_MAX_DEFERRAL_MIN", controller, 0, True, None),
        ],
    }
    for field, key, fields, minimum, allow_equal, percent in device_fields.get(device_type, ()):
        value = numeric(field, minimum, allow_equal=allow_equal, fields=fields)
        if value is not None:
            if percent is not None and value > percent:
                raise ValueError(f"{field} must be at most {percent}%")
            settings[key] = value / percent if percent else value

    if device_type == "HVAC":
        for field, key in (("min_indoor_temperature_f", "HVAC_MIN_TEMPERATURE_C"),
                           ("max_indoor_temperature_f", "HVAC_MAX_TEMPERATURE_C")):
            if controller.get(field) is not None:
                value = numeric(field, -459.67, allow_equal=False)
                settings[key] = (value - 32) * 5 / 9
        if settings.get("HVAC_MIN_TEMPERATURE_C", -np.inf) >= settings.get("HVAC_MAX_TEMPERATURE_C", np.inf):
            raise ValueError("Minimum indoor temperature must be below maximum")

    if device_type in {"HPWH", "ERWH"}:
        # Use the top tank node to check the minimum service temperature.
        # This is a zero-based index into OCHRE's tank temperature states.
        settings["WH_SERVICE_NODE_INDEX"] = 0
        settings["WH_LIMIT_MARGIN_C"] = 0.0
        minimum_f = controller.get("min_water_temperature_f")
        maximum_f = controller.get("max_water_temperature_f")

        def temperature(value):
            if isinstance(value, bool):
                raise ValueError("Temperature must be numeric")
            value = float(value)
            if not np.isfinite(value):
                raise ValueError("Temperature must be finite")
            return value

        if minimum_f is not None:
            minimum_f = temperature(minimum_f)
            settings["WH_MIN_TEMPERATURE_C"] = (
                minimum_f - 32.0
            ) * 5.0 / 9.0

        if maximum_f is not None:
            maximum_f = temperature(maximum_f)
            settings["WH_MAX_TEMPERATURE_C"] = (
                maximum_f - 32.0
            ) * 5.0 / 9.0

        if (
            minimum_f is not None
            and maximum_f is not None
            and minimum_f >= maximum_f
        ):
            raise ValueError(
                "Minimum water temperature must be below maximum"
            )

    return settings
