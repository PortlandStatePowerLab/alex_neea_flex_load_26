import datetime as dt
import math




def determine_control(device_modes, home_settings, CONFIG, sim_time):
    # Initialize control signal dictionary
    ctrl_signal = {}

    # Add Water Heating if simulated
    if CONFIG["WH_SIMULATION"] == "ON":
        ctrl_signal['Water Heating'] = {
            'Setpoint': CONFIG["WH_TbaselineC"],
            'Deadband': CONFIG["WH_TdeadbandC"],
            'Load Fraction': 1,
        }

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

    # Resolve only the participating device's selected mode/configuration.
    modes = {
        'ALU': ('ALUC', 'ALUdeadbandC'),
        'LU': ('LOADC', 'LOADdeadbandC'),
        'S': ('SHEDC', 'deadbandC'),
        'CP': ('CPC', 'CPdeadbandC'),
        'GE': ('GEC', 'GEdeadbandC'),
    }

    def get_mode(device):
        raw_mode = device_modes.get(device, 'NORMAL')
        mode = raw_mode.strip().upper() if isinstance(raw_mode, str) else raw_mode
        if not isinstance(mode, str) or (mode != 'NORMAL' and mode not in modes):
            raise ValueError(
                f"Unknown control mode {raw_mode!r} for {device}. "
                "Expected NORMAL, ALU, LU, S, CP, or GE."
            )
        return mode

    def apply_thermal_mode(device, end_use, prefix):
        mode = get_mode(device)
        if mode != 'NORMAL':
            sp_suffix, db_suffix = modes[mode]
            ctrl_signal[end_use].update({
                'Setpoint': CONFIG[prefix + '_Tcontrol_' + sp_suffix],
                'Deadband': CONFIG[prefix + '_Tcontrol_' + db_suffix],
            })

    if CONFIG["WH_SIMULATION"] == "ON":
        apply_thermal_mode('WH', 'Water Heating', 'WH')

    if CONFIG["HVAC_SIMULATION"] == "ON":
        if is_cooling_season:
            apply_thermal_mode('HVAC', 'HVAC Cooling', 'AC')
        else:
            apply_thermal_mode('HVAC', 'HVAC Heating', 'HEAT')

    # Dryers retain normal schedule operation and do not participate in modes.

    # EV ALU/LU retain the normal charging ceiling; S/CP/GE reduce it.
    if CONFIG["EV_SIMULATION"] == "ON" and home_settings.get("home_charger_kw") is not None:
        ctrl_signal['EV'] = {'Max Power': max(abs(home_settings["home_charger_kw"]), 0.001)}
        ev_mode = get_mode('EV')
        ev_fraction_keys = {'S': 'EV_SHED_PCT', 'CP': 'EV_CP_PCT', 'GE': 'EV_GE_PCT'}
        if ev_mode in ev_fraction_keys:
            fraction = CONFIG[ev_fraction_keys[ev_mode]]
            commanded_kw = abs(fraction * home_settings["home_charger_kw"])
            ctrl_signal['EV']['Max Power'] = max(commanded_kw, 0.001)

    if CONFIG["BATTERY_SIMULATION"] == "ON":
        battery_mode = get_mode('Battery')
        battery_p_keys = {
            'ALU': 'P_Battery_ALU_KW',
            'LU': 'P_Battery_LU_KW',
            'S': 'P_Battery_SHED_KW',
            'CP': 'P_Battery_CP_KW',
            'GE': 'P_Battery_GE_KW',
        }
        if battery_mode != 'NORMAL':
            ctrl_signal['Battery']['P Setpoint'] = CONFIG[battery_p_keys[battery_mode]]

    return ctrl_signal


DEVICE_END_USES = {
    "WH": ("Water Heating",), "HVAC": ("HVAC Heating", "HVAC Cooling"),
    "Dryer": ("Clothes Dryer",), "EV": ("EV",), "Battery": ("Battery",),
}


def advance_command_modes(state, requested_modes, sim_time, delays_seconds,
                          hold_minutes=0, safety_modes=None, eligible=None,
                          estimated_changes_kw=None):
    """Apply latest-request-wins delays and holds without advancing equipment.

    Repeating a pending request does not restart its timer. A request for the
    active mode cancels pending work. Safety modes bypass delays/holds and clear
    pending work. Eligibility is rechecked at activation; rejected work is cleared.
    Pending estimated_delta_kw is available for the dispatcher's response budget.
    Holds start at activation, apply to thermal devices only, and do not replace
    physical equipment cycling restrictions.
    """
    if not math.isfinite(hold_minutes) or hold_minutes < 0:
        raise ValueError("hold_minutes must be finite and nonnegative")
    safety_modes = safety_modes or {}
    estimated_changes_kw = estimated_changes_kw or {}
    allowed = {"NORMAL", "ALU", "LU", "S", "CP", "GE"}
    normalized = {}
    # Validate the entire request before mutating state.
    for device in requested_modes.keys() | safety_modes.keys():
        if device not in DEVICE_END_USES:
            raise ValueError(f"Unknown device {device}")
        mode = safety_modes.get(device, requested_modes.get(device, "NORMAL"))
        mode = mode.strip().upper() if isinstance(mode, str) else mode
        if not isinstance(mode, str) or mode not in allowed:
            raise ValueError(f"Unknown mode {mode!r} for {device}")
        delay = float(delays_seconds.get(device, 0))
        change = float(estimated_changes_kw.get(device, 0))
        if not math.isfinite(delay) or delay < 0 or not math.isfinite(change):
            raise ValueError(f"Invalid delay or estimated power for {device}")
        normalized[device] = (mode, delay, change)
    for device, (mode, delay, change) in normalized.items():
        item = state.setdefault(device, {"active_mode": "NORMAL", "pending": None,
                                         "activated_at": None, "hold_until": sim_time})
        if device in safety_modes:
            item.update(active_mode=mode, pending=None, activated_at=sim_time, hold_until=sim_time)
            continue
        if mode == item["active_mode"]:
            item["pending"] = None
            continue
        pending = item["pending"]
        if pending is None or pending["mode"] != mode:
            item["pending"] = {"mode": mode, "issued_at": sim_time,
                               "activate_at": max(sim_time + dt.timedelta(seconds=delay), item["hold_until"]),
                               "estimated_delta_kw": change}
    # Process due commands even if the caller submits no new requests this step.
    for device, item in state.items():
        pending = item["pending"]
        if pending is not None and sim_time >= pending["activate_at"]:
            if eligible is None or eligible(device, pending["mode"]):
                mode = pending["mode"]
                hold = hold_minutes if device in ("WH", "HVAC") and mode != "NORMAL" else 0
                item.update(active_mode=mode, activated_at=sim_time,
                            hold_until=sim_time + dt.timedelta(minutes=hold))
            item["pending"] = None
    return {device: item["active_mode"] for device, item in state.items()}


def control_for_home(home, settings, sim_time, baseline=False, requested_modes=None,
                     safety_modes=None, eligible=None, estimated_changes_kw=None):
    """Shared entry point: immediate NORMAL baseline, delayed controlled modes.

    Controlled callers must supply an eligibility check. They can inspect
    home['command_state'] for pending modes and estimated changes before dispatch.
    """
    info = home["home_info"]
    end_uses = set(info["participating_end_uses"])
    devices = {device for device, uses in DEVICE_END_USES.items() if end_uses.intersection(uses)}
    if baseline:
        modes = {device: "NORMAL" for device in devices}
    else:
        if eligible is None:
            raise ValueError("Controlled commands require an eligibility callback")
        requests = home.get("device_modes", {}) if requested_modes is None else requested_modes
        unknown = (set(requests) | set(safety_modes or {})) - devices
        if unknown:
            raise ValueError(f"Commands for absent or nonparticipating devices: {sorted(unknown)}")
        modes = advance_command_modes(
            home.setdefault("command_state", {}), requests, sim_time,
            info["response_delays_seconds"], settings.get("MIN_HOLD_MINUTES", 5),
            safety_modes, eligible, estimated_changes_kw)
    home["active_device_modes"] = modes
    config = dict(settings)
    for device, flag in (("WH", "WH_SIMULATION"), ("HVAC", "HVAC_SIMULATION"),
                         ("Dryer", "DRYER_SIMULATION"), ("EV", "EV_SIMULATION"),
                         ("Battery", "BATTERY_SIMULATION")):
        if device not in devices:
            config[flag] = "OFF"
    controls = determine_control(modes, info, config, sim_time)
    return {end_use: values for end_use, values in controls.items() if end_use in end_uses}
