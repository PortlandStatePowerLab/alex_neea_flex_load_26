# Read simulation parameters from Excel file
# Send simulation parameters to B_Common
# Read device parameters from Excel file
# Send device parameters to A3
# Send device parameters to B_Common
# Run A3
# Run B1
# Run controlled simulation B2
# Process data C1
# Plot data C5
# Calculate performance score C3
# Send reg cap / total power, performance score, and plots to Excel file

# device_parameters = {
#     "HPWH": {
#         "physical": {
#             "rated_compressor_power_w": None,
#             "rated_resistance_element_power_w": None,
#             "tank_volume_gal": None,
#             "rated_efficiency": {
#                 "type": None,   # "COP" or "UEF"
#                 "value": None,
#             },
#             "heating_capacity_btu_per_hr": None,
#         },
#         "controller": {
#             "max_water_temperature_f": None,
#             "min_water_temperature_f": None,
#             "response_time_s": None,
#             "control_interval_s": None,
#         },
#         **capability_fields(),
#     },

#     "ERWH": {
#         "physical": {
#             "heating_element_power_w": None,
#             "tank_volume_gal": None,
#             "heating_capacity_btu_per_hr": None,
#         },
#         "controller": {
#             "max_water_temperature_f": None,
#             "min_water_temperature_f": None,
#             "response_time_s": None,
#             "control_interval_s": None,
#         },
#         **capability_fields(),
#     },

#     "HVAC": {
#         "physical": {
#             "rated_electrical_power_w": None,
#             "heating_capacity_btu_per_hr": None,
#             "cooling_capacity_btu_per_hr": None,
#             "effective_building_thermal_capacity_kwh_per_f": None,
#         },
#         "controller": {
#             "minimum_modulation_pct": None,
#             "max_indoor_temperature_f": None,
#             "min_indoor_temperature_f": None,
#             "response_time_s": None,
#             "control_interval_s": None,
#         },
#         **capability_fields(),
#     },

#     "EV": {
#         "physical": {
#             "rated_charging_power_kw": None,
#             "maximum_battery_capacity_kwh": None,
#             "charging_efficiency_pct": None,
#         },
#         "controller": {
#             "usable_battery_flexibility_pct": None,
#             "response_time_s": None,
#             "control_interval_s": None,
#         },
#         **capability_fields(),
#     },

#     "Dryer": {
#         "physical": {
#             "rated_power_kw": None,
#             "cycle_energy_kwh": None,
#             "typical_cycle_duration_min": None,
#         },
#         "controller": {
#             "maximum_deferral_time_min": None,
#             "response_time_s": None,
#             "control_interval_s": None,
#         },
#         **capability_fields(),
#     },
# }


# EX A3 Usage:
from pathlib import Path
from uuid import uuid4
import A3_adjustXML as adj_xml
import argparse

# device_parameters = {}

# selected_device = "HPWH"

# summary = adj_xml.main(
#     device_type=selected_device,
#     parameters=device_parameters[selected_device],
#     output_dir=(
#         Path(__file__).resolve().parent.parent
#         / "HPWH Calculator Input Files"
#     ),
# )

# print("Prepared inputs:", summary["output_dir"])
# print("Applied parameters:", summary["parameters_applied"])
# print(
#     "Still requiring runtime handling:",
#     summary["runtime_parameters_not_applied"],
# )


import B2_Regulation as regulation
import B1_Baseline as baseline
import C1_parse_OCHRE_data_final as c1
import C4_Performance_Score as c4

def main(output_folder):
    output_folder = Path(output_folder).resolve()

    if not output_folder.is_dir():
        raise ValueError(f"Output folder does not exist: {output_folder}")

    output_folder = str(output_folder)

    print("Beginning OCHRE regulation simulation")

    # duration = int(input("Simulation duration [days]: "))
    # season = input("Season [Spring/Summer/Fall/Winter]: ").strip().title()
    season = "Winter"
    # Regulation window on day two; both full days are still simulated.
    # Use None for both settings to regulate throughout the full second day.
    regulation_start_time = "17:00"       # 24-hour clock, HH:MM
    regulation_duration_minutes = 120
    # weekday_text = input("Weekday? [yes/no]: ").strip().lower()
    # if weekday_text not in {"yes", "no"}:
    #     raise ValueError("Enter yes or no for weekday.")
    # weekday = weekday_text == "yes"
    weekday = True


    # reg_type = input("Regulation type [RegA/RegD]: ").strip()
    # output_folder = input("Output folder: ").strip()

    reg_type = "RegA"
    # output_folder = "Results_HPWH_full_fleet_test_11_13"

    device_parameters = {"HPWH": {
        "physical": {
            "rated_compressor_power_w": 450,
            "rated_resistance_element_power_w": 4500,
            "tank_volume_gal": 80,
            "rated_efficiency": {
                "type": "UEF",   # "COP" or "UEF"
                "value": 3.45,
            },
            "heating_capacity_btu_per_hr": None,
        },
        "controller": {
            "max_water_temperature_f": 150,
            "min_water_temperature_f": 95,
            "response_time_s": 30,
            "control_interval_s": 60,
        },
    }}

    selected_device = "HPWH"
    selected_parameters = device_parameters[selected_device]

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

    baseline_config = baseline.config_loading(
        Season=season,
        Weekday=weekday,
        REG_TYPE=reg_type,
        Output_Folder=output_folder,
        device_type=selected_device,
        device_parameters=selected_parameters,
        input_dir=prepared_dir,
    )

    regulation_config = regulation.config_loading(
        Season=season,
        Weekday=weekday,
        REG_TYPE=reg_type,
        Output_Folder=output_folder,
        device_type=selected_device,
        device_parameters=selected_parameters,
        input_dir=prepared_dir,
        regulation_start_time=regulation_start_time,
        regulation_duration_minutes=regulation_duration_minutes,
    )

    for label, config in (
        ("Baseline", baseline_config),
        ("Controlled", regulation_config),
    ):
        # print(f"\n{label} configuration:")
        # print(f"  Input directory: {config['INPUT_DIR']}")
        # print(
        #     "  Response time:",
        #     config.get("DEVICE_RESPONSE_TIME_S"),
        #     "seconds",
        # )
        # print(
        #     "  Control interval:",
        #     config.get("EFFECTIVE_CONTROL_INTERVAL_S"),
        #     "seconds",
        # )

        assert config["DEVICE_PARAMETERS"] == selected_parameters
        assert config["DEVICE_RESPONSE_TIME_S"] == 30
        assert config["CONTROL_INTERVAL_STEPS"] == 1

    # print(
    #     "\nPhysical inputs still requiring runtime handling:",
    #     prepared_inputs["runtime_parameters_not_applied"]["physical"],
    # )

        # Temporary validation settings.
    # for config in (baseline_config, regulation_config):
    #     config["NUM_HOMES"] = 50
    #     config["MIN_INITIALIZED_HOMES"] = 30

    summary, run_id = baseline.main()

    import pandas as pd

    capacity = pd.read_csv(summary["capacity_path"])

    # print("\nBaseline validation:")
    # print(f"Successful homes: {summary['homes_simulated']}")
    # print(f"Failed homes: {summary['homes_failed']}")

    for column in ("Up Capacity (kW)", "Down Capacity (kW)"):
        values = capacity[column]

        # print(f"\n{column}")
        # print(f"  Minimum: {values.min():.4f}")
        # print(f"  Mean: {values.mean():.4f}")
        # print(f"  Maximum: {values.max():.4f}")
        # print(f"  Fraction positive: {(values > 1e-9).mean():.1%}")
        # print(f"  10th percentile: {values.quantile(0.1):.4f}")

    # print("\nBaseline validation complete; B2 was not started.")
    # return
    # B2 also needs an existing baseline and a sine frequency.
    # baseline_run_id = input("Baseline run ID or full path: ").strip()
    # sine_freq = float(input("Sine frequency [cycles/minute]: "))
    sine_freq = 1.0 / 60.0

    # Use equal positive and negative power amplitudes for validation.
    regulation_config["REGULATION_CAPACITY_MODE"] = "symmetric"
    regulation_config["REGULATION_CAPACITY_FRACTION"] = 1.0
    _, results_dir = regulation.main(
        baseline_run_id=run_id,
        sine_freq=sine_freq,
    )

    c1.main(results_dir)
    perf_score = c4.main(run_dir=results_dir)

    # print(
    #     f"Baseline increased-consumption capacity: "
    #     f"{summary['up_regulation_capacity_kw']:.4f} kW"
    # )
    # print(
    #     f"Baseline decreased-consumption capacity: "
    #     f"{summary['down_regulation_capacity_kw']:.4f} kW"
    # )

    dispatched_capacity = min(
        summary["up_regulation_capacity_kw"],
        summary["down_regulation_capacity_kw"],
    ) * regulation_config["REGULATION_CAPACITY_FRACTION"]

    # print(
    #     f"Symmetric regulation amplitude used by B2: "
    #     f"±{dispatched_capacity:.4f} kW"
    # )
    # print(f"Performance Score: {perf_score:.6f}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-folder",
        required=True,
        help="Existing folder in which to store simulation results",
    )
    args = parser.parse_args()

    main(args.output_folder)

