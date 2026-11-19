import json
from pathlib import Path
from uuid import uuid4
import A3_adjustXML as adj_xml
import argparse

import B2_Regulation as regulation
import B1_Baseline as baseline
import C1_parse_OCHRE_data_final as c1
import C4_Performance_Score as c4
import C5_Normalized_Reg_Plt as c5

def main(output_folder, parameters, show_plots=False):
    output_folder = Path(output_folder).expanduser()
    if not output_folder.is_absolute():
        output_folder = Path(__file__).resolve().parent.parent / output_folder
    output_folder = output_folder.resolve()

    if not output_folder.is_dir():
        raise ValueError(f"Output folder does not exist: {output_folder}")

    output_folder = str(output_folder)

    print("Beginning OCHRE regulation simulation")

    # duration = int(input("Simulation duration [days]: "))
    # season = input("Season [Spring/Summer/Fall/Winter]: ").strip().title()
    # season = "Winter"
    # Regulation window on day two; both full days are still simulated.
    # Use None for both settings to regulate throughout the full second day.
    # regulation_start_time = "17:00"       # 24-hour clock, HH:MM
    # regulation_duration_minutes = 120
    # weekday_text = input("Weekday? [yes/no]: ").strip().lower()
    # if weekday_text not in {"yes", "no"}:
    #     raise ValueError("Enter yes or no for weekday.")
    # weekday = weekday_text == "yes"
    # weekday = True


    # output_folder = input("Output folder: ").strip()

    # output_folder = "Results_HPWH_full_fleet_test_11_13"

    # device_parameters = {"HPWH": {
    #     "physical": {
    #         "rated_compressor_power_w": 450,
    #         "rated_resistance_element_power_w": 4500,
    #         "tank_volume_gal": 80,
    #         "rated_efficiency": {
    #             "type": "COP",   # Rated heat-pump coefficient of performance
    #             "value": 3.45,
    #         },
    #         "heating_capacity_btu_per_hr": None,
    #     },
    #     "controller": {
    #         "max_water_temperature_f": 150,
    #         "min_water_temperature_f": 95,
    #         "response_time_s": 30,
    #         "control_interval_s": 60,
    #     },
    # }}

    # selected_device = "HPWH"
    # selected_parameters = device_parameters[selected_device]


    season = parameters["season"]
    weekday = parameters["weekday"]
    regulation_start_time = parameters["regulation_start_time"]
    regulation_duration_minutes = parameters["regulation_duration_minutes"]
    selected_parameters = parameters["device_parameters"]
    selected_device = parameters["selected_device"]

    # Isolate prepared inputs so another launch cannot overwrite this B1/B2 pair.
    prepared_inputs = adj_xml.main(
        device_type=selected_device,
        parameters=selected_parameters,
        output_dir=(
            Path(__file__).resolve().parent.parent
            / "Combo Regulation All Input Files"
            / f"f1_{uuid4().hex}"
        ),
    )

    prepared_dir = prepared_inputs["output_dir"]

    baseline.config_loading(
        Season=season,
        Weekday=weekday,
        Output_Folder=output_folder,
        device_type=selected_device,
        device_parameters=selected_parameters,
        input_dir=prepared_dir,
    )

    regulation_config = regulation.config_loading(
        Season=season,
        Weekday=weekday,
        Output_Folder=output_folder,
        device_type=selected_device,
        device_parameters=selected_parameters,
        input_dir=prepared_dir,
        regulation_start_time=regulation_start_time,
        regulation_duration_minutes=regulation_duration_minutes,
    )

    _, run_id = baseline.main()

    sine_freq = 1.0 / 60.0

    regulation_config["REGULATION_CAPACITY_MODE"] = "auto"
    regulation_config["REGULATION_CAPACITY_FRACTION"] = 1.0
    regulation_summary, results_dir = regulation.main(
        baseline_run_id=run_id,
        sine_freq=sine_freq,
    )

    c1.main(results_dir)
    up_cap = regulation_summary["up_regulation_capacity_kw"]
    down_cap = regulation_summary["down_regulation_capacity_kw"]
    dispatched_capacity = max(up_cap, down_cap)
    mode = regulation_summary["regulation_capacity_mode"]
    print(f"Regulation capacity ({mode}): +{up_cap:.4f} / -{down_cap:.4f} kW")
    perf_score = None
    if dispatched_capacity > 0:
        response = c5.main(run_dir=results_dir, no_show=not show_plots)
        if response["Target Delta (kW)"].abs().max() > 1e-9:
            perf_score = c4.main(run_dir=results_dir)
        else:
            print("No nonzero regulation target in the selected window. Performance score is unavailable.")
    else:
        print("No reliable regulation capacity in either direction. Performance score is unavailable.")

    results = {
        "output_folder": output_folder,
        "dispatched_capacity": dispatched_capacity,
        "up_regulation_capacity_kw": up_cap,
        "down_regulation_capacity_kw": down_cap,
        "regulation_capacity_mode": mode,
        "performance_score": perf_score
    }
    
    return results



if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-folder",
        required=True,
        help="Existing results folder; relative paths are resolved from OCHRE in Excel 111826",
    )
    parser.add_argument(
        "--show-plots", "--show_plots",
        action="store_true",
        help="Display the C5 normalized regulation plot (always saved to Ready_data).",
    )
    parser.add_argument(
        "--params",
        required=True,
        help="JSON dictionary of parameters for the simulation"
    )

    parser.add_argument("--results-file", type=Path, help="Write completed results as JSON")
    args = parser.parse_args()

    results = main(args.output_folder, json.loads(args.params), show_plots=args.show_plots)
    if args.results_file:
        args.results_file.write_text(json.dumps(results, allow_nan=False), encoding="utf-8")

