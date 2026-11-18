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
from pathlib import Path
import numpy as np
import json
import hashlib
import uuid
import copy
from time import perf_counter
from ochre.Equipment.EV import EV_EFFICIENCY
from tqdm import tqdm

import sys
import threading

import warnings

warnings.filterwarnings("ignore")


class OCHREOutputFilter:
    """
    Suppress OCHRE's normal console output while preserving:
      - user/application output
      - WARNING/ERROR tracebacks
      - simulation progress messages
    """

    def __init__(self, stream):
        self.stream = stream
        self.lock = threading.Lock()
        self.local = threading.local()

    def write(self, text):
        if not text:
            return 0

        if not hasattr(self.local, "buffer"):
            self.local.buffer = ""

        self.local.buffer += text

        while "\n" in self.local.buffer:

            line, self.local.buffer = (
                self.local.buffer.split("\n", 1)
            )

            if self._suppress(line):
                continue

            with self.lock:
                self.stream.write(line + "\n")
                self.stream.flush()

        return len(text)

    def flush(self):
        if hasattr(self.local, "buffer"):

            if self.local.buffer:
                line = self.local.buffer

                if not self._suppress(line):
                    with self.lock:
                        self.stream.write(line)
                        self.stream.flush()

                self.local.buffer = ""

        self.stream.flush()

    def _suppress(self, line):

        stripped = line.strip()

        if not stripped:
            return False

        upper_line = stripped.upper()

        # --------------------------------------------------------
        # Suppress all explicit WARNING messages
        # --------------------------------------------------------

        if "WARNING:" in upper_line:
            return True

        if "Removing previous results file:" in stripped:
            return True

        if "HPWH All Portland Input Files" in stripped:
            return True

        # --------------------------------------------------------
        # Suppress OCHRE initialization/status messages
        # --------------------------------------------------------

        if "OCHRE V" in upper_line:
            return True

        if stripped == "Dwelling Initialized":
            return True

        if stripped.startswith("Initializing Base_"):
            return True

        if stripped.startswith("Initializing Ctrl_"):
            return True

        if ("baseline_bldg" in stripped or "controlled_bldg" in stripped) and "2018-" in stripped:
            return True

        if "OCHREException" in stripped:
            return True

        # OCHRE dwelling timestamp/status lines
        if (
            ("Base_bldg" in stripped or "Ctrl_bldg" in stripped)
            and "2018-" in stripped
        ):
            return True

        return False
    def __getattr__(self, name):
        return getattr(self.stream, name)

sys.stdout = OCHREOutputFilter(sys.stdout)
sys.stderr = OCHREOutputFilter(sys.stderr)



# Settings and reusable setup are owned by B_Common.
# B2 tracks a regulation signal using capacity and reference power exported by B1.
try:
    from . import B_Common as common
    from .B_ControlSignals import control_for_home, determine_control, DEVICE_END_USES
except ImportError:
    import B_Common as common
    from B_ControlSignals import control_for_home, determine_control, DEVICE_END_USES

CONFIG = None


def config_loading(
    Season,
    Weekday,
    REG_TYPE,
    Output_Folder,
    device_type,
    device_parameters,
    input_dir,
    regulation_start_time=None,
    regulation_duration_minutes=None,
):
    global CONFIG

    config = common.load_configuration(
        Season, Weekday, REG_TYPE, Output_Folder
    )

    CONFIG = common.apply_device_parameters(
        config,
        device_type,
        device_parameters,
        input_dir,
    )

    # Optional clock time on B1's reporting day (day two).
    CONFIG["REGULATION_START_TIME"] = regulation_start_time
    CONFIG["REGULATION_DURATION_MINUTES"] = regulation_duration_minutes

    # B1's saved manifest defines the fleet and its initialization settings.
    return CONFIG

# create_home_schedule = common.create_home_schedule
count = 0

#########################################
# SCHEDULE FILTERING
#########################################

def _action_context(home, device, mode, sim_time, settings):
    """Validate a request and find actual, enabled electric equipment."""
    if device not in DEVICE_END_USES:
        raise ValueError(f"Unknown device {device!r}")
    if not isinstance(mode, str) or mode.strip().upper() not in {"NORMAL", "LU", "S"}:
        raise ValueError("Regulation actions support NORMAL, LU, and S only")
    mode = mode.strip().upper()
    participating = home["home_info"]["participating_end_uses"]
    equipment = []
    for eq in home["controlled"].equipment.values():
        if eq.end_use not in DEVICE_END_USES[device] or eq.end_use not in participating:
            continue
        if settings[common.FLEX_END_USES[eq.end_use][1]] != "ON" or not eq.is_electric:
            continue
        if device == "HVAC":
            seasonal_use = "HVAC Cooling" if sim_time.month in (5, 6, 7, 8, 9) else "HVAC Heating"
            if eq.end_use != seasonal_use:
                continue
        equipment.append(eq)
    return mode, equipment


def _action_delta_kw(home, device, mode, sim_time, settings, equipment):
    """Approximate target-mode power minus measured power; never update equipment.

    Thermal deadband behavior is conservative. EV estimates cover the current
    charging event only, not future events or departure-energy guarantees.
    """
    controls = determine_control({device: mode}, home["home_info"], settings, sim_time)
    total = 0.0
    for eq in equipment:
        power = _capacity_number(getattr(eq, "electric_kw", None))
        if power is None:
            return 0.0
        command = controls.get(eq.end_use, {})
        if device in ("WH", "HVAC"):
            # Reuse the existing conservative thermostat estimates with both
            # thresholds set to the requested mode, including NORMAL release.
            prefix = "WH" if device == "WH" else ("HEAT" if eq.end_use == "HVAC Heating" else "AC")
            target_settings = dict(settings)
            for suffix in ("_Tcontrol_LOADC", "_Tcontrol_SHEDC"):
                target_settings[prefix + suffix] = command["Setpoint"]
            for suffix in ("_Tcontrol_LOADdeadbandC", "_Tcontrol_deadbandC"):
                target_settings[prefix + suffix] = command["Deadband"]
            timed_home = dict(home, sim_time=sim_time)
            if device == "WH":
                up, down = estimate_wh_regulation_capacity_kw(timed_home, eq, target_settings)
            else:
                up, down = _estimate_hvac_capacity_kw(timed_home, eq, target_settings, prefix == "HEAT")
            delta = up - down
            # OCHRE retains the physical mode until its minimum run/off time.
            minimum = getattr(eq, "min_time_in_mode", {}).get(getattr(eq, "mode", None))
            elapsed = getattr(eq, "time_in_mode", None)
            if delta and minimum is not None and elapsed is not None and elapsed < minimum:
                return 0.0
        elif device == "Battery":
            soc = _capacity_number(getattr(eq, "soc", None))
            if soc is None or not 0 <= soc <= 1:
                return 0.0
            low, high = copy.copy(eq).get_power_limits()
            if not np.isfinite([low, high]).all() or low > high:
                return 0.0
            target = _capacity_number(command.get("P Setpoint"))
            if target is None:
                return 0.0
            delta = min(high, max(low, target)) - power
        elif device == "EV":
            if not getattr(eq, "in_event", False):
                return 0.0
            # Do not estimate across an event boundary using stale event state.
            event_end = getattr(eq, "event_end", None)
            if event_end is not None and sim_time >= event_end:
                return 0.0
            soc = _capacity_number(getattr(eq, "soc", None))
            capacity = _capacity_number(getattr(eq, "capacity", None))
            soc_max = _capacity_number(getattr(eq, "soc_max_ctrl", None))
            ceiling = _capacity_number(command.get("Max Power"))
            hours = float(settings["t_res"]) / 60
            if (None in (soc, capacity, soc_max, ceiling) or hours <= 0
                    or not 0 <= soc <= 1 or not 0 <= soc_max <= 1 or capacity <= 0):
                return 0.0
            energy_limit = max(0.0, soc_max - soc) * capacity / hours / EV_EFFICIENCY
            delta = min(ceiling, energy_limit) - power
        else:
            return 0.0  # Dryer modes do not change power yet.
        total += delta
    return float(total)


def thermal_mode_allowed(
    home, device, mode, sim_time, settings
):
    """Check water-heater regulation operating limits."""
    if device != "WH" or mode == "NORMAL":
        return True

    minimum = settings.get("WH_MIN_TEMPERATURE_C")
    maximum = settings.get("WH_MAX_TEMPERATURE_C")

    # Preserve existing behavior if no limits were supplied.
    if minimum is None and maximum is None:
        return True

    if minimum is None or maximum is None:
        raise ValueError("Both WH temperature limits are required")

    margin = float(settings.get("WH_LIMIT_MARGIN_C", 0.0))
    minimum = float(minimum)
    maximum = float(maximum)

    if (
        not np.isfinite([minimum, maximum, margin]).all()
        or margin < 0
        or minimum + margin >= maximum - margin
    ):
        raise ValueError("Invalid WH temperature limits or margin")

    node_index = settings["WH_SERVICE_NODE_INDEX"]

    if (
        isinstance(node_index, bool)
        or not isinstance(node_index, int)
        or node_index < 0
    ):
        raise ValueError("Invalid WH service-node index")

    _, equipment = _action_context(
        home, device, mode, sim_time, settings
    )

    if not equipment:
        return False

    for eq in equipment:
        temperatures = np.asarray(
            getattr(getattr(eq, "model", None), "states", []),
            dtype=float,
        )

        if (
            temperatures.ndim != 1
            or temperatures.size <= node_index
            or not np.isfinite(temperatures).all()
        ):
            raise ValueError(
                "Missing or invalid water-heater node temperatures"
            )

        service_temperature = float(temperatures[node_index])
        hottest_temperature = float(temperatures.max())

        if mode == "S":
            if service_temperature <= minimum + margin:
                return False

        elif mode == "LU":
            if hottest_temperature >= maximum - margin:
                return False

        else:
            raise ValueError(
                f"Unsupported regulation mode: {mode}"
            )

    return True


def device_eligibility(home, device, mode, sim_time, settings=None):
    """Whether a NORMAL/LU/S request may activate now.

    Use as control_for_home's eligibility callback. Delays/pending activation
    are owned by that helper; this function does not mutate command state.
    NORMAL releases remain allowed even when no power response is predicted.
    Safety releases should use control_for_home's separate safety_modes input.
    """
    settings = CONFIG if settings is None else settings
    mode, equipment = _action_context(home, device, mode, sim_time, settings)
    if not equipment:
        return False
    if not thermal_mode_allowed(
        home, device, mode, sim_time, settings
    ):
        return False
    state = home.get("command_state", {}).get(device, {})
    active = state.get("active_mode", "NORMAL")
    hold_until = state.get("hold_until")
    if mode != active and hold_until is not None and sim_time < hold_until:
        return False
    if mode == "NORMAL":
        return True
    if device == "Dryer":
        return False
    delta = _action_delta_kw(home, device, mode, sim_time, settings, equipment)
    return delta > 1e-9 if mode == "LU" else delta < -1e-9


def action_estimation(home, device, mode, sim_time, settings=None):
    """Return incremental kW for a new eligible action (+ load, - shed).

    Active and already-pending identical requests return zero so dispatch does
    not count them again. Pending response must be budgeted separately. This
    is not response relative to B1 or a sustained-capacity guarantee.
    """
    settings = CONFIG if settings is None else settings
    mode, equipment = _action_context(home, device, mode, sim_time, settings)
    if not thermal_mode_allowed(
        home, device, mode, sim_time, settings
    ):
        return 0.0
    state = home.get("command_state", {}).get(device, {})
    if mode == state.get("active_mode", "NORMAL"):
        return 0.0
    pending = state.get("pending")
    if pending is not None and mode == pending["mode"]:
        return 0.0
    # Context is already validated above. Avoid repeating the equipment scan
    # and (for thermal devices) calculating the same response twice per action.
    hold_until = state.get("hold_until")
    if (not equipment or device == "Dryer"
            or (hold_until is not None and sim_time < hold_until)):
        return 0.0
    delta = _action_delta_kw(home, device, mode, sim_time, settings, equipment)
    if mode == "NORMAL":
        return delta
    return delta if (delta > 1e-9 if mode == "LU" else delta < -1e-9) else 0.0


def _normalise_reg_signal(reg_sig):
    value = float(reg_sig)
    if not np.isfinite(value):
        raise ValueError("Regulation signal must be finite")
    return max(-1.0, min(1.0, value))


def _dispatch_devices(home):
    """Device groups actually participating in this home."""
    uses = set(home["home_info"]["participating_end_uses"])
    return [device for device, end_uses in DEVICE_END_USES.items()
            if device != "Dryer" and uses.intersection(end_uses)]


def _dispatch_candidates(fleet_data, sim_time, settings):
    """One or more alternatives per device; dispatcher selects at most one."""
    candidates = []
    for index, home in enumerate(fleet_data):
        for device in _dispatch_devices(home):
            if device in home.get("safety_modes", {}):
                continue  # The worker applies the explicit safety override.
            state = home.get("command_state", {}).get(device, {})
            if state.get("pending") is not None:
                continue
            active = state.get("active_mode", "NORMAL")

            # Consider every alternative to the active command.
            # action_estimation applies operating limits and cycling checks.
            modes = tuple(
                mode
                for mode in ("NORMAL", "LU", "S")
                if mode != active
            )
            for mode in modes:
                delta = action_estimation(home, device, mode, sim_time, settings)
                if not np.isfinite(delta):
                    raise ValueError(f"Nonfinite action estimate for {device}")
                if abs(delta) > 1e-9:
                    candidates.append({"home": home, "index": index, "device": device,
                                       "mode": mode, "delta_kw": delta,
                                       "headroom": _thermal_headroom(home, device, mode, sim_time, settings),
                                       "count": home.get("device_dispatch_counts", {}).get(device, 0)})
    return candidates


def estimate_up_capacity_kw(fleet_data, CONFIG, sim_time):
    candidates = _dispatch_candidates(fleet_data, sim_time, CONFIG)
    return sum(max(0.0, action["delta_kw"]) for action in candidates)


def estimate_down_capacity_kw(fleet_data, CONFIG, sim_time):
    candidates = _dispatch_candidates(fleet_data, sim_time, CONFIG)
    return sum(max(0.0, -action["delta_kw"]) for action in candidates)


def _thermal_headroom(home, device, mode, sim_time, settings):
    """Temperature margin toward the requested setpoint; larger is preferred."""
    if device not in ("WH", "HVAC") or mode == "NORMAL" or "controlled" not in home:
        return 0.
    _, equipment = _action_context(home, device, mode, sim_time, settings)
    controls = determine_control({device: mode}, home["home_info"], settings, sim_time)
    margins = []
    for eq in equipment:
        if device == "WH":
            values = np.asarray(getattr(getattr(eq, "model", None), "states", []), dtype=float)
            if not values.size or not np.isfinite(values).all():
                continue
            temperature = float(values.mean())
        else:
            temperature = float(eq.zone.temperature)
        direction = -1 if eq.end_use == "HVAC Cooling" else 1
        margin = direction * (controls[eq.end_use]["Setpoint"] - temperature)
        margins.append(max(0., margin if mode == "LU" else -margin))
    return min(margins, default=0.)


def _response_steps(home, device, sim_time, settings):
    delay = float(home["home_info"].get("response_delays_seconds", {}).get(device, 0))
    if not np.isfinite(delay) or delay < 0:
        raise ValueError("Invalid response delay")
    return int(np.ceil(delay / (60 * float(settings["t_res"]))))


def _continuous_limits(home, device, sim_time, settings):
    """Safe instantaneous bounds; no mutation of OCHRE state."""
    _, equipment = _action_context(home, device, "NORMAL", sim_time, settings)
    if len(equipment) != 1:
        return None
    eq = equipment[0]
    power = float(eq.electric_kw)
    if device == "Battery":
        low, high = copy.copy(eq).get_power_limits()
        low = max(low, settings["P_Battery_SHED_KW"])
        high = min(high, settings["P_Battery_LU_KW"])
    else:
        if not getattr(eq, "in_event", False) or sim_time >= eq.event_end:
            return None
        hours = float(settings["t_res"]) / 60
        energy = max(0., eq.soc_max_ctrl - eq.soc) * eq.capacity / hours / EV_EFFICIENCY
        high = min(home["home_info"]["home_charger_kw"], getattr(eq, "max_power", float("inf")), energy)
        low = min(high, max(.001, settings["EV_SHED_PCT"] * home["home_info"]["home_charger_kw"]))
    if not np.isfinite([power, low, high]).all() or low > high:
        raise ValueError("Invalid continuous limits")
    return power, float(low), float(high)



def _energy_weight(home, device, direction, sim_time, settings):
    """Directional energy margin, used for sharing rather than a hard reserve."""
    _, equipment = _action_context(home, device, "NORMAL", sim_time, settings)
    eq = equipment[0]
    soc = float(getattr(eq, "soc", .5))
    low = float(getattr(eq, "soc_min", 0.))
    high = float(getattr(eq, "soc_max_ctrl", getattr(eq, "soc_max", 1.)))
    margin = high - soc if direction > 0 else soc - low
    capacity = float(getattr(eq, "capacity", 1.))
    return max(1e-6, margin * capacity)


def _share_continuous(entries, total, sim_time, settings):
    """Bounded fleet allocation. Battery recovery is offset within the same target.

    entries contain (home, device, measured power, low, high). No future samples
    or baseline device states are used. Recovery never changes the fleet request.
    """
    if not entries:
        return []
    low = np.array([e[3] for e in entries], dtype=float)
    high = np.array([e[4] for e in entries], dtype=float)
    power = np.array([e[2] for e in entries], dtype=float)
    desired = power.copy()
    hours = float(settings.get("ENERGY_RECOVERY_HOURS", 2.))
    if not np.isfinite(hours) or hours <= 0:
        raise ValueError("ENERGY_RECOVERY_HOURS must be positive")
    for i, (home, device, _, _, _) in enumerate(entries):
        if device == "Battery":
            _, equipment = _action_context(home, device, "NORMAL", sim_time, settings)
            eq = equipment[0]
            midpoint = (float(getattr(eq, "soc_min", 0.)) + float(getattr(eq, "soc_max", 1.))) / 2
            desired[i] = (midpoint - float(eq.soc)) * float(getattr(eq, "capacity", 1.)) / hours
    commands = np.clip(desired, low, high)
    target = float(np.clip(power.sum() + total, low.sum(), high.sum()))
    for _ in range(len(entries) + 1):
        residual = target - commands.sum()
        if abs(residual) < 1e-9:
            break
        room = high - commands if residual > 0 else commands - low
        weights = np.array([_energy_weight(e[0], e[1], residual, sim_time, settings)
                            for e in entries]) * (room > 1e-9)
        if weights.sum() == 0:
            break
        changes = np.minimum(room, abs(residual) * weights / weights.sum())
        commands += changes if residual > 0 else -changes
    return commands.tolist()


def dispatch_regulation_signal(fleet_data, reg_sig, previous_actual_delta_kw,
                               UP_REG_CAP, DWN_REG_CAP, CONFIG, sim_time):
    """Request per-device modes without advancing dwellings or delay timers.

    Positive response means increased consumption. Feedback uses the previous
    measured fleet response plus activation-time-bucketed pending response.
    Future targets use causal slope extrapolation, never future signal samples. Estimates are not guaranteed delivered or sustained power.
    Call once per control interval, before all workers advance that timestep.
    """
    signal = _normalise_reg_signal(reg_sig)
    measured = float(previous_actual_delta_kw)
    up_cap, down_cap = float(UP_REG_CAP), float(DWN_REG_CAP)
    gain = float(CONFIG["FEEDBACK_GAIN"])
    deadband = float(CONFIG["TRACKING_DEADBAND_KW"])
    configured_limit = CONFIG["MAX_RESPONSE_CHANGE_KW_PER_INTERVAL"]
    # A reversal can require moving across both directional capacities in
    # one interval. Preserve explicit limits for ramp-constrained studies.
    limit = up_cap + down_cap if configured_limit is None else float(configured_limit)
    if (not np.isfinite([measured, up_cap, down_cap, gain, deadband, limit]).all()
            or min(up_cap, down_cap, deadband, limit) < 0 or not 0 <= gain <= 1):
        raise ValueError("Invalid dispatch capacities, feedback settings, or measured response")
    target = signal * (up_cap if signal >= 0 else down_cap)
    pending_by_step = {}
    pending_kw = 0.0
    canceled = 0
    for home in fleet_data:
        # Only changed/new requests are submitted. This avoids reissuing a
        # rejected request forever or canceling a retained delayed command.
        home["device_modes"] = {}
        home["estimated_changes_kw"] = {}
        for device in _dispatch_devices(home):
            state = home.get("command_state", {}).get(device, {})
            pending = state.get("pending")
            if pending is None:
                continue
            change = float(pending.get("estimated_delta_kw", 0.0))
            if not np.isfinite(change):
                raise ValueError(f"Nonfinite pending estimate for {device}")
            # Budget retained commands against the remaining error, including
            # commands already retained for other homes. A falling target can
            # make a same-direction queue excessive even without a reversal.
            # Requesting the active mode clears that pending timer in the worker.
            due = pending.get("activate_at", sim_time)
            k = max(0, int(np.ceil((due - sim_time).total_seconds() / (60 * CONFIG["t_res"]))))
            future_signal = np.clip(signal + k * home.get("regulation_signal_slope", 0.), -1., 1.)
            future_target = future_signal * (up_cap if future_signal >= 0 else down_cap)
            remaining = future_target - measured - sum(v for step, v in pending_by_step.items() if step <= k)
            if (device in home.get("safety_modes", {})
                    or abs(remaining) <= deadband
                    or change * remaining <= 0
                    or abs(remaining - change) >= abs(remaining) - 1e-9):
                home["device_modes"][device] = state.get("active_mode", "NORMAL")
                canceled += 1
            else:
                pending_by_step[k] = pending_by_step.get(k, 0.) + change
                if k == 0:
                    pending_kw += change

    predicted = measured + pending_kw
    error = target - predicted
    requested = float(np.clip(gain * error, -limit, limit)) if abs(error) > deadband else 0.0
    candidates = _dispatch_candidates(fleet_data, sim_time, CONFIG)
    if CONFIG.get("CONTINUOUS_POWER_CONTROL", True):
        candidates = [c for c in candidates if not (
            c["device"] in ("Battery", "EV") and "controlled" in c["home"]
            and _response_steps(c["home"], c["device"], sim_time, CONFIG) == 0
            and _continuous_limits(c["home"], c["device"], sim_time, CONFIG) is not None)]
    available_up = sum(max(0.0, c["delta_kw"]) for c in candidates)
    available_down = sum(max(0.0, -c["delta_kw"]) for c in candidates)
    # Prefer faster response, closer power fit, then least-used devices.
    candidates.sort(key=lambda c: (
        _response_steps(c["home"], c["device"], sim_time, CONFIG),
        -c.get("headroom", 0.) if CONFIG.get("ENERGY_AWARE_DISPATCH", True) else 0.,
        c["count"], abs(requested - c["delta_kw"]), c["index"], c["device"]))
    applied = 0.0
    spent = 0.0
    applied_by_step = {}
    used = set()
    selected = []
    for candidate in candidates:
        key = (candidate["index"], candidate["device"])
        delta = candidate["delta_kw"]
        k = _response_steps(candidate["home"], candidate["device"], sim_time, CONFIG)
        future_signal = np.clip(signal + k * candidate["home"].get("regulation_signal_slope", 0.), -1., 1.)
        future_target = future_signal * (up_cap if future_signal >= 0 else down_cap)
        prediction = measured + sum(v for step, v in pending_by_step.items() if step <= k)
        remaining = float(np.clip(gain * (future_target - prediction), -limit, limit))
        remaining -= sum(v for step, v in applied_by_step.items() if step <= k)
        if key in used or abs(remaining) <= deadband or delta * remaining <= 0:
            continue
        if spent + abs(delta) > limit + 1e-9:
            continue
        # A discrete action may overshoot only if it improves the mismatch.
        if abs(remaining - delta) >= abs(remaining) - 1e-9:
            continue
        home, device, mode = candidate["home"], candidate["device"], candidate["mode"]
        home["device_modes"][device] = mode
        home["estimated_changes_kw"][device] = delta
        counts = home.setdefault("device_dispatch_counts", {})
        counts[device] = counts.get(device, 0) + 1
        used.add(key)
        applied += delta
        spent += abs(delta)
        applied_by_step[k] = applied_by_step.get(k, 0.) + delta
        selected.append({"home": home.get("path", candidate["index"]),
                         "device": device, "mode": mode, "estimated_delta_kw": delta})


    continuous = []
    if CONFIG.get("CONTINUOUS_POWER_CONTROL", True):
        for home in fleet_data:
            home["continuous_power_kw"] = {}
            if "controlled" not in home:
                continue
            for device in ("EV", "Battery"):
                if (device not in _dispatch_devices(home) or device in home.get("safety_modes", {})
                        or _response_steps(home, device, sim_time, CONFIG) != 0):
                    continue
                bounds = _continuous_limits(home, device, sim_time, CONFIG)
                if bounds is not None:
                    continuous.append((home, device, *bounds))
        budget = max(0., limit - spent)
        remaining = float(np.clip(requested - applied_by_step.get(0, 0.), -budget, budget))
        if abs(remaining) <= deadband:
            remaining = 0.
        if CONFIG.get("ENERGY_AWARE_DISPATCH", True):
            commands = _share_continuous(continuous, remaining, sim_time, CONFIG)
            # Counteracting recovery commands must also respect the gross ramp budget.
            gross = sum(abs(command - entry[2]) for command, entry in zip(commands, continuous))
            if gross > budget + 1e-9:
                commands = []  # Fall back to monotonic allocation under an explicit ramp limit.
        else:
            commands = []
        if not commands:
            for home, device, power, low, high in continuous:
                command = float(np.clip(power + remaining, low, high))
                commands.append(command)
                remaining -= command - power
        for (home, device, power, low, high), command in zip(continuous, commands):
            available_up += max(0., high - power)
            available_down += max(0., power - low)
            delta = command - power
            home["continuous_power_kw"][device] = command
            home["device_modes"].pop(device, None)
            home["estimated_changes_kw"].pop(device, None)
            applied += delta
            spent += abs(delta)
            applied_by_step[0] = applied_by_step.get(0, 0.) + delta
            if abs(delta) > 1e-9:
                selected.append({"home": home.get("path"), "device": device,
                                 "mode": "POWER", "estimated_delta_kw": delta})

    device_diagnostics = {}
    for device in ("WH", "HVAC", "EV", "Battery"):
        alternatives = [c for c in candidates if c["device"] == device]
        bounds = [e for e in continuous if e[1] == device]
        device_diagnostics[device + "_available_up_kw"] = sum(max(0., c["delta_kw"]) for c in alternatives) + sum(max(0., e[4]-e[2]) for e in bounds)
        device_diagnostics[device + "_available_down_kw"] = sum(max(0., -c["delta_kw"]) for c in alternatives) + sum(max(0., e[2]-e[3]) for e in bounds)
        device_diagnostics[device + "_dispatched_delta_kw"] = sum(c["estimated_delta_kw"] for c in selected if c["device"] == device)

    return {**device_diagnostics, "reg_sig": signal, "target_delta_kw": target,
            "previous_actual_delta_kw": measured, "pending_delta_kw": pending_kw,
            "predicted_delta_kw": predicted,
            "future_pending_delta_kw": sum(pending_by_step.values()) - pending_kw, "feedback_error_kw": error,
            "requested_adjustment_kw": requested, "applied_adjustment_kw": applied,
            "available_up_kw": available_up, "available_down_kw": available_down,
            "estimated_response_after_pending_kw": measured + sum(pending_by_step.values()) + applied,
            "predicted_current_delta_kw": predicted + applied_by_step.get(0, 0.),
            "dispatched_units": len(selected), "canceled_pending": canceled,
            "controller_saturated": (abs(gain * error) > limit + 1e-9
                                     or abs(requested - applied_by_step.get(0, 0.)) > deadband),
            "actions": selected}


def regulation_window(times, config):
    """Select [start, end) on day two; retain the full OCHRE simulation grid."""
    times = pd.DatetimeIndex(times)
    start_text = config.get("REGULATION_START_TIME")
    minutes = config.get("REGULATION_DURATION_MINUTES")
    if start_text is None and minutes is None:
        return times
    if start_text is None or minutes is None:
        raise ValueError("Provide both regulation_start_time and regulation_duration_minutes")
    try:
        clock = dt.datetime.strptime(start_text, "%H:%M").time()
        if isinstance(minutes, bool):
            raise ValueError()
        minutes = float(minutes)
    except (TypeError, ValueError):
        raise ValueError("Use start time HH:MM and a positive duration in minutes") from None
    if not np.isfinite(minutes) or minutes <= 0:
        raise ValueError("Regulation duration must be finite and positive")
    start = times[0].normalize() + pd.Timedelta(hours=clock.hour, minutes=clock.minute)
    end = start + pd.Timedelta(minutes=minutes)
    cadence = pd.Timedelta(minutes=config["t_res"])
    if start < times[0] or end > times[-1] + cadence:
        raise ValueError("Regulation window must fit within B1's saved reporting period")
    if (start - times[0]) % cadence or (end - start) % cadence:
        raise ValueError("Regulation start and duration must align with the simulation timestep")
    selected = times[(times >= start) & (times < end)]
    if selected.empty:
        raise ValueError("Regulation window contains no simulation timestamps")
    return selected


def load_reg_sig(reg_type, CONFIG, sine_freq):
    reg_sig = common.configure_regulation(reg_type, CONFIG["REG_DIR"], CONFIG["Start"], CONFIG["Duration"], CONFIG["t_res"], sine_freq)

    if reg_sig is None:
        raise ValueError(f"Failed to load regulation signal for type: {reg_type}")

    return reg_sig

def load_baseline_run(run_id):
    """Load a completed B1 run and validate the fleet/time/capacity contract."""
    root = Path(CONFIG.get("RESULTS_DIR", Path(__file__).resolve().parent / "Results"))
    run_path = Path(run_id)
    if not run_path.is_absolute():
        run_path = root / run_path
    manifest = json.loads((run_path / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "complete":
        raise ValueError("B1 baseline run must be complete")
    entries = manifest.get("homes", [])
    names = [entry["name"] for entry in entries]
    homes = [entry["path"] for entry in entries]
    if (not names or len(names) != len(set(names)) or len(homes) != len(set(homes))
            or len(names) != manifest["summary"]["homes_simulated"]):
        raise ValueError("Invalid baseline manifest fleet")
    baseline = pd.read_csv(
        run_path / "baseline.csv",
        usecols=[
            "Time",
            "Home",
            "Total Electric Power (kW)",
            "Water Heating Electric Power (kW)",
        ],
    )
    capacity = pd.read_csv(run_path / "capacity.csv")
    times = pd.date_range(manifest["time_start"], periods=manifest["time_steps"],
                          freq=dt.timedelta(minutes=CONFIG["t_res"]))
    if times.empty or times[-1] != pd.Timestamp(manifest["time_end"]):
        raise ValueError("Baseline reporting grid is invalid")
    baseline["Time"] = pd.to_datetime(baseline["Time"], errors="raise")
    if set(baseline["Home"]) != set(names):
        raise ValueError("Baseline CSV homes do not match the manifest")
    for name, frame in baseline.groupby("Home", sort=False):
        validate_results(
            frame,
            times,
            name,
            [
                "Total Electric Power (kW)",
                "Water Heating Electric Power (kW)",
            ],
        )
    capacity = validate_results(capacity, times, "B1 capacity",
                                ["Up Capacity (kW)", "Down Capacity (kW)", "Homes"])
    if ((capacity[["Up Capacity (kW)", "Down Capacity (kW)"]] < 0).any().any()
            or not capacity["Homes"].eq(len(homes)).all()):
        raise ValueError("Invalid baseline capacity or fleet size")
    quantile = float(manifest["summary"]["capacity_availability_quantile"])
    if not np.isfinite(quantile) or not 0 <= quantile <= 1:
        raise ValueError("Invalid B1 capacity quantile")
    for column, key in (("Up Capacity (kW)", "up_regulation_capacity_kw"),
                        ("Down Capacity (kW)", "down_regulation_capacity_kw")):
        value = float(manifest["summary"][key])
        if not np.isfinite(value) or value < 0 or not np.isclose(value, capacity[column].quantile(quantile)):
            raise ValueError(f"B1 summary does not match {column}")
    return baseline, capacity, manifest, homes


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
    # Start in NORMAL; regulation requests are submitted by the timestep loop.
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
        controlled_dw, home_info = common.init_home(
            home,
            CONFIG,
            prepare_schedules(home),
            run_kind="controlled"
        )
        device_modes = {device: "NORMAL" for device, uses in DEVICE_END_USES.items()
                        if set(uses).intersection(home_info["participating_end_uses"])}

        return {
            "success": True,
            "controlled": controlled_dw,
            "path": home,
            "last_controlled_kw": 0.0,
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
    return common.aggregate_home_results(
        homes, work_dir, expected_times, required_by_home, "controlled", validate_results)


def temperature_release_modes(home, sim_time, settings):
    """Return immediate NORMAL releases for prohibited WH modes."""
    if "WH" not in _dispatch_devices(home):
        return {}

    state = home.get("command_state", {}).get("WH", {})

    modes_to_check = [
        state.get("active_mode", "NORMAL"),
    ]

    pending = state.get("pending")
    if pending is not None:
        modes_to_check.append(pending["mode"])

    for mode in modes_to_check:
        if not thermal_mode_allowed(
            home, "WH", mode, sim_time, settings
        ):
            return {"WH": "NORMAL"}

    return {}


def update_home_worker(home_data, sim_time):
    """Apply queued device controls, advance a dwelling, and read equipment states."""
    try:
        home_data["sim_time"] = sim_time
        dwelling = home_data["controlled"]
        if dwelling.current_time != sim_time:
            raise ValueError(f"Dwelling time {dwelling.current_time} != {sim_time}")
        temperature_releases = temperature_release_modes(
            home_data, sim_time, CONFIG
        )

        # Preserve other safety rules. NORMAL is the temperature-release
        # policy here; resolve priorities explicitly if you later add
        # other WH emergency modes.
        safety_modes = dict(home_data.get("safety_modes", {}))
        safety_modes.update(temperature_releases)
        control = control_for_home(
            home_data, CONFIG, sim_time, baseline=False,
            eligible=lambda device, mode: device_eligibility(home_data, device, mode, sim_time),
            safety_modes=safety_modes,
            estimated_changes_kw=home_data.get("estimated_changes_kw"))
        continuous_commands = home_data.setdefault(
            "continuous_power_kw", {}
        )

        # Safety releases must also clear held continuous commands.
        # Otherwise an old command could return after safety clears.
        for device in home_data.get("safety_modes", {}):
            continuous_commands.pop(device, None)

        for device, power in continuous_commands.items():
            if device == "Battery":
                control["Battery"] = {"P Setpoint": power}
            elif device == "EV":
                control["EV"] = {"Max Power": power}
        # Requests are one-shot; active/pending modes live in command_state.
        home_data["device_modes"] = {}
        home_data["estimated_changes_kw"] = {}
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
        wh_power = _capacity_number(
            metrics.get("Water Heating Electric Power (kW)")
        )
        if wh_power is None:
            raise ValueError("Missing/nonfinite water-heater power")

        return {
            "success": True,
            "controlled_kw": power,
            "controlled_wh_kw": wh_power,
            "devices": devices,
        }
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
    settings = CONFIG if settings is None else settings

    return common.estimate_wh_regulation_capacity_kw(
        home, wh, settings
    )

def _estimate_hvac_capacity_kw(home, equipment, settings, heating):
    """Approximate LU/S headroom from thermostat thresholds and current rating."""
    power = _capacity_number(getattr(equipment, "electric_kw", None))
    temperature = _capacity_number(getattr(getattr(equipment, "zone", None), "temperature", None))
    if power is None or temperature is None or getattr(equipment, "is_gas", False):
        return 0.0, 0.0
    sim_time = home.get("sim_time")
    if sim_time is None:
        sim_time = getattr(home.get("controlled"), "current_time", None)
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
        for equipment in home["controlled"].equipment.values():
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


def _run_regulation(run_dir, manifest, run_id, sine_freq):
    started = perf_counter()
    baseline_csv, baseline_cap_csv, manifest_baseline, baseline_homes = load_baseline_run(run_id)
    homes = baseline_homes
    # Reuse the successful baseline fleet, which can be smaller than NUM_HOMES
    # when B1 permits initialization failures. These are selection settings,
    # not independent choices for the controlled run.
    for key in ("NUM_HOMES", "MIN_INITIALIZED_HOMES"):
        if key in manifest_baseline["configuration"]:
            CONFIG[key] = manifest_baseline["configuration"][key]
    baseline_summary = manifest_baseline["summary"]
    up_cap = float(baseline_summary["up_regulation_capacity_kw"])
    down_cap = float(baseline_summary["down_regulation_capacity_kw"])
    fraction = float(CONFIG.get("REGULATION_CAPACITY_FRACTION", 1.0))
    if not np.isfinite(fraction) or not 0 < fraction <= 1:
        raise ValueError("REGULATION_CAPACITY_FRACTION must be in (0, 1]")
    mode = CONFIG.get("REGULATION_CAPACITY_MODE", "asymmetric")
    if mode not in ("asymmetric", "symmetric"):
        raise ValueError("REGULATION_CAPACITY_MODE must be asymmetric or symmetric")
    if mode == "symmetric":
        up_cap = down_cap = min(up_cap, down_cap)
    manifest["regulation_capacity_mode"] = mode
    up_cap *= fraction
    down_cap *= fraction
    manifest["regulation_capacity_fraction"] = fraction
    baseline_power = baseline_csv.groupby("Time")["Total Electric Power (kW)"].sum()

    baseline_wh_power = baseline_csv.groupby("Time")[
        "Water Heating Electric Power (kW)"
    ].sum()

    manifest["tracking_power_basis"] = "Water Heating Electric Power (kW)"
    manifest["tracking_scope"] = (
        "HPWH-only diagnostic; whole-home response recorded separately"
    )
    
    output_times = regulation_window(baseline_cap_csv["Time"], CONFIG)
    manifest["regulation_start"] = str(output_times[0])
    manifest["regulation_end_exclusive"] = str(
        output_times[-1] + pd.Timedelta(minutes=CONFIG["t_res"]))
    manifest["baseline_run_id"] = manifest_baseline["run_id"]
    manifest["capacity_basis"] = "B1 reliable instantaneous LU/S capacity quantile; positive means increased consumption"
    manifest["up_regulation_capacity_kw"] = up_cap
    manifest["down_regulation_capacity_kw"] = down_cap
    # Reusing capacity requires the same physical simulation and control settings.
    baseline_config = manifest_baseline["configuration"]
    ignored = {"REG_TYPE", "REG_SIGNAL", "REG_ADDRESS", "REG_DIR", "RESULTS_DIR",
               "FEEDBACK_GAIN", "TRACKING_DEADBAND_KW", "MAX_RESPONSE_CHANGE_KW_PER_INTERVAL",
               "FLEET_WORKERS", "NUMERICAL_THREADS", "MIN_HOLD_MINUTES", "MIN_HOLD_STEPS",
               "REGULATION_CAPACITY_FRACTION", "CONTINUOUS_POWER_CONTROL", "CAUSAL_LOOKAHEAD",
               "ENERGY_AWARE_DISPATCH", "ENERGY_RECOVERY_HOURS", "REGULATION_CAPACITY_MODE"}
    current_config = json.loads(json.dumps(CONFIG, default=str))
    for key, value in baseline_config.items():
        current_value = current_config.get(key)
        if isinstance(value, str) and isinstance(current_value, str) and ("\\" in value or "/" in value):
            value = os.path.normcase(os.path.normpath(value))
            current_value = os.path.normcase(os.path.normpath(current_value))
        if key not in ignored and key in current_config and current_value != value:
            raise ValueError(f"Configuration differs from B1: {key}")
    if not homes:
        raise RuntimeError(f"No valid homes in {CONFIG['INPUT_DIR']}")
    # No example homes are copied into the selected fleet.
    if not Path(CONFIG["WEATHER_FILE"]).is_file():
        raise FileNotFoundError(CONFIG["WEATHER_FILE"])
    manifest["weather_sha256"] = _file_hash(CONFIG["WEATHER_FILE"])
    if manifest["weather_sha256"] != manifest_baseline["weather_sha256"]:
        raise ValueError("Weather file differs from B1")
    for entry in manifest_baseline["homes"]:
        for filename, key in ((CONFIG["XML_ADDRESS"], "xml_sha256"),
                              (CONFIG["CSV_ADDRESS"], "schedule_sha256")):
            if _file_hash(Path(entry["path"]) / filename) != entry[key]:
                raise ValueError(f"Input differs from B1: {entry['name']} / {filename}")
    manifest["homes"] = []
    manifest["initialization_failures"] = []
    manifest["homes_requested"] = manifest_baseline["summary"]["homes_simulated"]
    fleet_data = []
    # print(f"Initializing {len(homes)} homes serially...", flush=True)
    with tqdm(
        total=len(homes),
        desc="B2 initializing homes",
        unit="home",
        file=sys.__stderr__,
        dynamic_ncols=True,
        bar_format=(
            "{desc}: {percentage:3.0f}%|{bar}| "
            "{n_fmt}/{total_fmt} "
            "[Elapsed: {elapsed} | ETR: {remaining}]"
        ),
    ) as progress:
        for i, home in enumerate(homes, 1):
            result = init_fleet_worker(home)
            if not result["success"]:
                manifest["initialization_failures"].append({"path": str(Path(home).resolve()), "error": result["error"]})
                raise RuntimeError("Initialization canceled: homes failed")
            fleet_data.append(result)
            manifest["homes"].append({
                "name": Path(home).name, "path": str(Path(home).resolve()),
                "xml_sha256": _file_hash(Path(home) / CONFIG["XML_ADDRESS"]),
                "schedule_sha256": _file_hash(Path(home) / CONFIG["CSV_ADDRESS"]),
                "prepared_schedule_sha256": _file_hash(Path(home) / "baseline_schedules.csv"),
                "home_info": result["home_info"],
            })
            progress.update(1)
    if not fleet_data:
        raise RuntimeError("No homes initialized successfully; cannot simulate an empty fleet")
    homes = [home["path"] for home in fleet_data]

    for i in range(len(homes)):
        if homes[i] != baseline_homes[i]:
            raise RuntimeError(f"Home does not match baseline home")

    # print(f"Initialization complete: {len(homes)} successful", flush=True)
    sim_times = pd.DatetimeIndex(fleet_data[0]["controlled"].sim_times)
    if sim_times.empty or sim_times.hasnans or not sim_times.is_unique:
        raise ValueError("Invalid simulation time grid")
    expected = pd.date_range(sim_times[0], periods=len(sim_times), freq=dt.timedelta(minutes=CONFIG["t_res"]))
    if not sim_times.equals(expected):
        raise ValueError("Irregular simulation time grid")
    for home in fleet_data:
        if not sim_times.equals(pd.DatetimeIndex(home["controlled"].sim_times)):
            raise ValueError(f"Mismatched time grid: {home['path']}")
    # WetAppliance uses global random draws during updates. Fail explicitly rather
    # than claim reproducibility for that model under threaded stepping.
    for home in fleet_data:
        if any(type(eq).__module__.endswith("WetAppliance") for eq in home["controlled"].equipment.values()):
            raise ValueError("WetAppliance requires isolated random generators before threaded baseline updates")
    reporting_grid = sim_times[(sim_times >= output_times[0]) & (sim_times <= output_times[-1])]
    if not reporting_grid.equals(output_times):
        raise ValueError("Controlled reporting grid does not match B1")
    signal = load_reg_sig(CONFIG["REG_TYPE"], CONFIG, sine_freq).copy()
    signal.index = pd.to_datetime(signal.index, errors="raise")
    if not signal.index.is_unique:
        raise ValueError("Duplicate regulation signal timestamps")
    signal = signal.reindex(output_times)
    if not np.isfinite(signal.to_numpy(dtype=float)).all():
        raise ValueError("Regulation signal must cover every B1 reporting timestamp")
    manifest["time_start"] = str(output_times[0])
    manifest["time_end"] = str(output_times[-1])
    manifest["time_steps"] = len(output_times)
    rows = []
    previous_actual = 0.0
    previous_signal = None
    target_energy_kwh = actual_energy_kwh = 0.
    simulation_started = perf_counter()
    manifest["timings_seconds"] = {"setup": simulation_started - started}
    interval_steps = CONFIG.get("CONTROL_INTERVAL_STEPS", 1)

    if (
        isinstance(interval_steps, bool)
        or not isinstance(interval_steps, int)
        or interval_steps < 1
    ):
        raise ValueError("CONTROL_INTERVAL_STEPS must be a positive integer")

    reporting_step = 0
    with (
        common.numerical_threads(CONFIG),
        common.fleet_executor(CONFIG) as executor,
        tqdm(
            total=len(sim_times),
            desc="B2 regulation simulation",
            unit="step",
            file=sys.__stderr__,
            dynamic_ncols=True,
            bar_format=(
                "{desc}: {percentage:3.0f}%|{bar}| "
                "{n_fmt}/{total_fmt} "
                "[Elapsed: {elapsed} | ETR: {remaining}]"
            ),
        ) as progress,
    ):
        for step, sim_time in enumerate(sim_times, 1):
            reporting = output_times[0] <= sim_time <= output_times[-1]
            if not reporting:
                # End regulation immediately: cancel delayed requests and held modes.
                # Continue stepping every dwelling normally through both full days.
                for home in fleet_data:
                    home["command_state"] = {}
                    home["device_modes"] = {}
                    home["estimated_changes_kw"] = {}
                    home["continuous_power_kw"] = {}
                    home["regulation_signal_slope"] = 0.0
            if reporting:
                current_signal = _normalise_reg_signal(signal.loc[sim_time])

                # Update the signal slope every simulation step.
                # Existing lookahead calculations use slope per simulation step.
                slope = (
                    0.0
                    if previous_signal is None
                    else current_signal - previous_signal
                )

                for home in fleet_data:
                    home["regulation_signal_slope"] = (
                        slope if CONFIG.get("CAUSAL_LOOKAHEAD", True) else 0.0
                    )

                previous_signal = current_signal

                dispatch_due = reporting_step % interval_steps == 0
                reporting_step += 1

                # The tracking target updates every simulation step,
                # even when the controller cannot issue a new command.
                current_target_kw = current_signal * (
                    up_cap if current_signal >= 0 else down_cap
                )

                if dispatch_due:
                    dispatch = dispatch_regulation_signal(
                        fleet_data,
                        current_signal,
                        previous_actual,
                        up_cap,
                        down_cap,
                        CONFIG,
                        sim_time,
                    )
                else:
                    # No new discrete requests. The existing command queue
                    # still retains active modes and pending activations.
                    for home in fleet_data:
                        home["device_modes"] = {}
                        home["estimated_changes_kw"] = {}

                    # Record only diagnostics that are meaningful this step.
                    dispatch = {
                        "reg_sig": current_signal,
                        "target_delta_kw": current_target_kw,
                        "previous_actual_delta_kw": previous_actual,
                        "requested_adjustment_kw": 0.0,
                        "applied_adjustment_kw": 0.0,
                        "dispatched_units": 0,
                        "canceled_pending": 0,
                        "actions": [],
                    }

            results = common.step_fleet(
                executor,
                update_home_worker,
                fleet_data,
                sim_time,
            )
            
            if reporting:
                whole_controlled_kw = sum(
                    result["controlled_kw"] for result in results
                )
                whole_base_kw = float(baseline_power.loc[sim_time])

                controlled_kw = sum(
                    result["controlled_wh_kw"] for result in results
                )
                base_kw = float(baseline_wh_power.loc[sim_time])

                # Feedback now measures the participating water heaters.
                previous_actual = controlled_kw - base_kw
                row = {"Time": sim_time, "Up Capacity (kW)": up_cap,
                       "Down Capacity (kW)": down_cap, "Homes": len(fleet_data),
                       "Baseline Power (kW)": base_kw, "Controlled Power (kW)": controlled_kw,
                       "Actual Delta (kW)": previous_actual,
                       "Tracking Error (kW)": dispatch["target_delta_kw"] - previous_actual}
                row.update({
                    "Tracking Power Basis": "Water Heating",
                    "Whole-home Baseline Power (kW)": whole_base_kw,
                    "Whole-home Controlled Power (kW)": whole_controlled_kw,
                    "Whole-home Actual Delta (kW)": (
                        whole_controlled_kw - whole_base_kw
                    ),
                })
                target_energy_kwh += dispatch["target_delta_kw"] * CONFIG["t_res"] / 60
                actual_energy_kwh += previous_actual * CONFIG["t_res"] / 60
                row["Cumulative Target Energy (kWh)"] = target_energy_kwh
                row["Cumulative Actual Delta Energy (kWh)"] = actual_energy_kwh
                row["Dispatch Update"] = dispatch_due
                row.update({key: value for key, value in dispatch.items() if key != "actions"})
                rows.append(row)
            progress.update(1)
    export_started = perf_counter()
    manifest["timings_seconds"]["simulation"] = export_started - simulation_started
    required_by_home = {}
    with tqdm(
        total=len(fleet_data),
        desc="B2 finalizing homes",
        unit="home",
        file=sys.__stderr__,
        dynamic_ncols=True,
        bar_format=(
            "{desc}: {percentage:3.0f}%|{bar}| "
            "{n_fmt}/{total_fmt} "
            "[Elapsed: {elapsed} | ETR: {remaining}]"
        ),
    ) as progress:
        for home in fleet_data:
            name = Path(home["path"]).name
            frame, _, _ = home["controlled"].finalize()
            required = ["Total Electric Power (kW)", "Total Electric Energy (kWh)"]
            for end_use in home["home_info"]["participating_end_uses"]:
                required.append(end_use + " Electric Power (kW)")
            for end_use in ("EV", "Battery"):
                if end_use in home["home_info"]["participating_end_uses"]:
                    required.append(end_use + " SOC (-)")
            frame = restore_time_column(frame, name)
            frame = frame.loc[frame["Time"].isin(output_times)].copy()
            frame = validate_results(frame, output_times, name, required)
            # Retain temperatures and other diagnostics in addition to required power.
            destination = run_dir / "homes" / name
            destination.mkdir(parents=True, exist_ok=True)
            frame.to_csv(destination / "home_controlled.csv", index=False)
            required_by_home[name] = required
            progress.update(1)
    controlled_path = aggregate_results(homes, run_dir, output_times, required_by_home)
    capacities = pd.DataFrame(rows)
    capacity_path = run_dir / "regulation_capacity.csv"
    capacities.to_csv(capacity_path, index=False)
    quantile = float(baseline_summary["capacity_availability_quantile"])
    tracking_path = run_dir / "regulation_tracking.csv"
    capacities.to_csv(tracking_path, index=False)
    try:
        from .B_TrackingMetrics import tracking_metrics
    except ImportError:
        from B_TrackingMetrics import tracking_metrics
    diagnostics = tracking_metrics(capacities, CONFIG["t_res"])
    (run_dir / "tracking_summary.json").write_text(
        json.dumps(diagnostics, indent=2, allow_nan=False), encoding="utf-8")
    manifest["tracking_metrics"] = diagnostics
    summary = {
        "baseline_run_id": manifest_baseline["run_id"], "tracking_path": str(tracking_path),
        "homes_simulated": len(homes), "homes_failed": len(manifest["initialization_failures"]),
        "controlled_path": controlled_path, "capacity_path": str(capacity_path),
        "manifest_path": str(run_dir / "regulation_manifest.json"),
        "capacity_availability_quantile": quantile,
        "up_regulation_capacity_kw": up_cap,
        "down_regulation_capacity_kw": down_cap,
    }
    manifest["summary"] = summary
    manifest["timings_seconds"]["export"] = perf_counter() - export_started
    # print(f"Run timings (seconds): {manifest['timings_seconds']}", flush=True)
    return summary


def main(baseline_run_id, sine_freq, reg_type=None):
    # print("Beginning Controlled simulation...")
    if CONFIG is None:
        raise RuntimeError("Call config_loading() before main()")
    if reg_type is not None:
        CONFIG["REG_TYPE"] = reg_type
    minimum_homes = CONFIG["MIN_INITIALIZED_HOMES"]
    if isinstance(minimum_homes, bool) or not isinstance(minimum_homes, int) or minimum_homes < 0:
        raise ValueError("MIN_INITIALIZED_HOMES must be a nonnegative integer")
    quantile = float(CONFIG["RELIABLE_CAPACITY_QUANTILE"])
    if not np.isfinite(quantile) or not 0 <= quantile <= 1:
        raise ValueError("RELIABLE_CAPACITY_QUANTILE must be between 0 and 1")
    # Save each controlled attempt in a new subfolder of its B1 baseline.
    root = Path(CONFIG.get("RESULTS_DIR", Path(__file__).resolve().parent / "Results"))
    run_dir = Path(baseline_run_id)
    if not run_dir.is_absolute():
        run_dir = root / run_dir
    run_dir = run_dir.resolve()
    baseline_manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if baseline_manifest.get("status") != "complete":
        raise ValueError("B1 baseline run must be complete")
    baseline_dir = run_dir
    run_id = "controlled_" + dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid.uuid4().hex[:8]
    run_dir = baseline_dir / run_id
    run_dir.mkdir(exist_ok=False)
    lock_path = run_dir / "regulation.lock"
    with lock_path.open("x", encoding="utf-8") as stream:
        stream.write(str(os.getpid()))
    manifest = {"run_id": run_id, "baseline_run_id": baseline_manifest["run_id"],
                "baseline_path": str(baseline_dir), "status": "running", "configuration": CONFIG,
                "capacity_basis": "Instantaneous LU/S estimates; excludes response delay and sustained-service guarantees"}
    try:
        (run_dir / "regulation_manifest.json").write_text(
            json.dumps(manifest, indent=2, default=str), encoding="utf-8")
        with common.numerical_threads(CONFIG):
            result = _run_regulation(run_dir, manifest, str(baseline_dir), sine_freq)
        manifest["status"] = "complete"
        # print(f"Regulation results saved: {result['controlled_path']}", flush=True)
        return result, baseline_dir
    except Exception as exc:
        manifest.update(status="failed", error=repr(exc))
        raise
    finally:
        try:
            (run_dir / "regulation_manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
        finally:
            lock_path.unlink()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run regulation using a completed Combo B1 baseline")
    parser.add_argument("--baseline-run-id", required=True, help="B1 result directory name or absolute path")
    parser.add_argument("--reg-type", choices=("RegA", "RegD"), default=None)
    parser.add_argument("--sine-freq", type=float, default=0.1, help="Sine frequency in cycles per minute (below 0.5 / t_res)")
    parser.add_argument("--capacity-mode", choices=("asymmetric", "symmetric"), default=None)
    args = parser.parse_args()
    if args.capacity_mode is not None:
        CONFIG["REGULATION_CAPACITY_MODE"] = args.capacity_mode
    main(args.baseline_run_id, args.sine_freq, args.reg_type)
    # print("Simulation finished.", flush=True)
