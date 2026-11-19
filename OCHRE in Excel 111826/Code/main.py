import json
import tempfile
import argparse
from datetime import datetime, time
import math
from pathlib import Path
import subprocess
import sys


# params:
# season, reg start time, reg duration, weekday/weekend, selected device
# device parameters
def read_device_params(pyvals_sheet, selected_device):
    """Translate workbook parameter keys to the selected device's F1 schema."""
    physical_fields = {
        "HPWH": {
            "CompPwr": "rated_compressor_power_w",
            "ResistPwr": "rated_resistance_element_power_w",
            "TankVol": "tank_volume_gal",
            "HeatCap": "heating_capacity_btu_per_hr",
        },
        "ERWH": {
            "HeatElePwr": "heating_element_power_w",
            "TankVol": "tank_volume_gal",
            "HeatCap": "heating_capacity_btu_per_hr",
        },
        "HVAC": {
            "ElectPwr": "rated_electrical_power_w",
            "HeatCap": "heating_capacity_btu_per_hr",
            "CoolCap": "cooling_capacity_btu_per_hr",
            "BuildCap": "effective_building_thermal_capacity_kwh_per_f",
        },
        "EV": {
            "ChargePwr": "rated_charging_power_kw",
            "BattCap": "maximum_battery_capacity_kwh",
            "ChargeEffic": "charging_efficiency_pct",
        },
        "Dryer": {
            "RatedPwr": "rated_power_kw",
            "CycleEnergy": "cycle_energy_kwh",
            "TypCycDur": "typical_cycle_duration_min",
        },
        "Battery": {
            "RatedPwr": "rated_power_kw",
            "UsableEnergyCap": "usable_energy_capacity_kwh",
        },
    }
    controller_fields = {
        "HPWH": {"MaxWaterTemp": "max_water_temperature_f",
                 "MinWaterTemp": "min_water_temperature_f"},
        "ERWH": {"MaxCntrlWaterTemp": "max_water_temperature_f",
                 "MinCntrlWaterTemp": "min_water_temperature_f"},
        "HVAC": {"MinMod": "minimum_modulation_pct",
                 "MaxIndoorTemp": "max_indoor_temperature_f",
                 "MinIndoorTemp": "min_indoor_temperature_f"},
        "EV": {"BattFlex": "usable_battery_flexibility_pct"},
        "Dryer": {"MaxDefTime": "maximum_deferral_time_min"},
        "Battery": {
            "SoCOpRng": "soc_operating_range_pct",
            "MaxRespTime": "response_time_s",
            "RecoveryRate": "recovery_rate_kw",
            "CommInt": "control_interval_s",
        },
    }
    if selected_device not in physical_fields:
        raise ValueError(f"Unsupported device parameter mapping: {selected_device!r}")
    mapping = {
        key.casefold(): ("physical", field)
        for key, field in physical_fields[selected_device].items()
    }
    controller = {
        **controller_fields[selected_device],
        "RespTime": "response_time_s",
        "CntrlInt": "control_interval_s",
    }
    mapping.update({key.casefold(): ("controller", field)
                    for key, field in controller.items()})
    # Also accept schema field names for callers using an updated workbook.
    mapping.update({field.casefold(): (section, field)
                    for section, field in list(mapping.values())})
    result = {"physical": {}, "controller": {}}
    import math
    for row in range(7, 16):
        key = pyvals_sheet.range(f"B{row}").value
        cell = pyvals_sheet.range(f"C{row}")
        value = cell.value
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        normalized_key = str(key or "").strip().casefold()
        efficiency = selected_device == "HPWH" and normalized_key in {"copuef", "cop", "rated cop"}
        if not efficiency and normalized_key not in mapping:
            raise ValueError(
                f"Unknown {selected_device} parameter in 'Python Values'!B{row}: {key!r}"
            )
        try:
            if (selected_device == "Battery"
                    and mapping[normalized_key][1] == "soc_operating_range_pct"):
                if isinstance(value, str):
                    parts = value.replace("%", "").replace("–", "-").split("-")
                    if len(parts) == 2:
                        number = [float(endpoint) for endpoint in parts]
                    else:
                        number = float(parts[0]) if len(parts) == 1 else None
                elif isinstance(value, bool):
                    raise ValueError()
                else:
                    factor = 100 if "%" in str(getattr(cell, "number_format", "")) else 1
                    number = float(value) * factor
                endpoints = number if isinstance(number, list) else [number]
                if number is None or not all(math.isfinite(endpoint) for endpoint in endpoints):
                    raise ValueError()
            else:
                if isinstance(value, bool):
                    raise ValueError()
                percent_field = not efficiency and mapping[normalized_key][1].endswith("_pct")
                if percent_field and isinstance(value, str) and value.strip().endswith("%"):
                    number = float(value.strip()[:-1])
                else:
                    number = float(value)
                    if percent_field and not isinstance(value, str) and "%" in str(
                        getattr(cell, "number_format", "")
                    ):
                        number *= 100
                if not math.isfinite(number):
                    raise ValueError()
        except (TypeError, ValueError):
            raise ValueError(
                f"Invalid 'Python Values'!C{row} value for {key}: {value!r}."
            ) from None
        if efficiency:
            section, field = "physical", "rated_efficiency"
            number = {"type": "COP",
                      "value": number}
        else:
            section, field = mapping[normalized_key]
        if field in result[section]:
            raise ValueError(f"Duplicate {selected_device} parameter: {key!r}")
        result[section][field] = number
    return result


def read_regulation_start_time(value):
    """Convert an Excel clock value to the minute-aligned HH:MM used by B2."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, datetime):
        value = value.time()
    if isinstance(value, time) and value.second == value.microsecond == 0:
        return value.strftime("%H:%M")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value < 1:
        minutes = round(value * 1440)
        if minutes < 1440 and math.isclose(value * 1440, minutes, rel_tol=0, abs_tol=1e-6):
            return f"{minutes // 60:02d}:{minutes % 60:02d}"
    if isinstance(value, str):
        for pattern in ("%H:%M", "%I:%M %p"):
            try:
                return datetime.strptime(value.strip(), pattern).strftime("%H:%M")
            except ValueError:
                pass
    raise ValueError("'Python Values'!C4 must contain a clock time on a whole minute, such as 17:00.")


def read_Excel(pyvals_sheet):
    season = str(pyvals_sheet.range("C2").value or "").strip().title()
    if season not in {"Spring", "Summer", "Fall", "Winter"}:
        raise ValueError("'Python Values'!C2 must contain Spring, Summer, Fall, or Winter.")
    day_type = pyvals_sheet.range("C3").value
    if isinstance(day_type, str):
        label = day_type.strip().casefold()
        day_type = {
            "weekday": True, "weekend": False,
            "true": True, "false": False, "yes": True, "no": False,
            "1": True, "0": False,
        }.get(label)
    if not isinstance(day_type, (bool, int, float)) or day_type not in (0, 1):
        raise ValueError("'Python Values'!C3 must contain Weekday or Weekend.")
    weekday = bool(day_type)
    regulation_start_time = read_regulation_start_time(pyvals_sheet.range("C4").value)
    regulation_duration_minutes = pyvals_sheet.range("C5").value
    device_label = pyvals_sheet.range("C6").value
    device_names = {
        "hpwh": "HPWH",
        "heat pump water heater": "HPWH",
        "heat pump water heaters": "HPWH",
        "erwh": "ERWH",
        "electric resistance water heater": "ERWH",
        "electric resistance water heaters": "ERWH",
        "hvac": "HVAC",
        "heating ventilation and air conditioning": "HVAC",
        "heating ventilation air conditioning": "HVAC",
        "ev": "EV",
        "ev charger": "EV",
        "electric vehicle": "EV",
        "electric vehicles": "EV",
        "electric vehicle charger": "EV",
        "dryer": "Dryer",
        "dryers": "Dryer",
        "clothes dryer": "Dryer",
        "clothes dryers": "Dryer",
        "battery": "Battery",
        "batteries": "Battery",
        "battery energy storage": "Battery",
        "battery energy storage system": "Battery",
    }
    # Normalize Excel labels while keeping the exact identifiers F1 expects.
    device_key = " ".join(
        str(device_label or "").casefold().replace("-", " ")
        .replace(",", " ").replace("&", " and ").split()
    )
    try:
        selected_device = device_names[device_key]
    except KeyError:
        raise ValueError(
            f"Unsupported flex load in 'Python Values'!C6: {device_label!r}. "
            "Choose Heat Pump Water Heater, Electric Resistance Water Heater, "
            "HVAC, Electric Vehicle, Dryer, or Battery."
        ) from None

    device_params = read_device_params(pyvals_sheet, selected_device)
    
    params = {
        "season": season,
        "weekday": weekday,
        "regulation_start_time": regulation_start_time,
        "regulation_duration_minutes": regulation_duration_minutes,
        "selected_device": selected_device,
        "device_parameters": device_params
    }

    # print(params)

    return params



def write_Excel(calc_sheet, results):
    calc_sheet.range("N29").value = results["dispatched_capacity"] #dispatched capacity
    calc_sheet.range("N30").value = results["performance_score"] #performance score
    calc_sheet.range("N48").value = results["output_folder"] #output folder

    plot_name = "OCHRE_Normalized_Regulation_Plot"
    plot_path = results["regulation_plot_path"]
    if plot_path is not None:
        anchor = calc_sheet.range("R2")
        picture = calc_sheet.pictures.add(
            plot_path, name=plot_name, update=True, anchor=anchor, width=504,
        )
        # xlwings preserves the old position on update. Reset it to R2.
        picture.left = anchor.left
        picture.top = anchor.top
    elif plot_name in calc_sheet.pictures:
        calc_sheet.pictures[plot_name].delete()


def main():
    from Setup import setup_env

    parser = argparse.ArgumentParser(description="Prepare OCHRE and run F1 with a monitor")
    parser.add_argument("--workbook", help="Optional Excel workbook to read")
    parser.add_argument("--params", help="JSON simulation parameters when no workbook is supplied")
    parser.add_argument("--output-folder", help="Existing results folder; prompts when omitted")
    parser.add_argument("--show-plots", "--show_plots", action="store_true")
    parser.add_argument("--inside-monitor", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--environment-ready", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if not args.inside_monitor:
        monitor_script = Path(__file__).resolve().parent / "Setup" / "monitor.py"
        command = [
            sys.executable, "-u", str(monitor_script),
            "--py_exe", sys.executable, "--script", str(Path(__file__).resolve()),
            "--script-args", "--inside-monitor", *sys.argv[1:],
        ]
        subprocess.run(command, check=True, cwd=setup_env.PROJECT_FOLDER)
        return

    if not args.workbook and not args.params:
        from tkinter import Tk
        from tkinter.filedialog import askopenfilename
        dialog = Tk()
        dialog.withdraw()
        try:
            args.workbook = askopenfilename(
                title="Select OCHRE calculator workbook", parent=dialog,
                initialdir=setup_env.PROJECT_FOLDER,
                filetypes=[("Excel workbooks", "*.xlsm *.xlsx")],
            )
        finally:
            dialog.destroy()
        if not args.workbook:
            raise RuntimeError("No workbook selected; simulation cancelled.")

    if not args.environment_ready:
        python_venv = setup_env.prepare_environment()
        command = [str(python_venv), "-u", str(Path(__file__).resolve()),
                   "--environment-ready", "--inside-monitor"]
        if args.workbook:
            command.extend(["--workbook", str(Path(args.workbook).resolve())])
        if args.output_folder:
            command.extend(["--output-folder", args.output_folder])
        if args.params:
            command.extend(["--params", args.params])
        if args.show_plots:
            command.append("--show-plots")
        subprocess.run(command, check=True, cwd=setup_env.PROJECT_FOLDER)
        return

    results_folder = setup_env.resolve_results_folder(args.output_folder)
    params = json.loads(args.params) if args.params else None
    if args.workbook:
        import xlwings as xw
        wb = xw.Book(args.workbook)
        params = read_Excel(wb.sheets("Python Values"))


    if params is None:
        parser.error("Supply --workbook or --params for F1 simulation parameters.")
    with tempfile.TemporaryDirectory(prefix="ochre_results_") as handoff:
        results_file = Path(handoff) / "results.json"
        setup_env.run_script(
            sys.executable, results_folder, show_plots=args.show_plots,
            params=json.dumps(params, default=str), results_file=results_file,
            monitored=False,
        )
        if not results_file.is_file():
            raise RuntimeError("F1 did not produce completed results; Excel was not updated.")
        results = json.loads(results_file.read_text(encoding="utf-8"))
    if args.workbook:
        write_Excel(wb.sheets("Calculator"), results)
    print(json.dumps(results), flush=True)
    return results


if __name__ == "__main__":
    main()
