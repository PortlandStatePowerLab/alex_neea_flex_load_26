"""
Author: Alex Wardwell
Created: 8/10/26

Runs OCHRE from Excel.

@modified by: 
@modified date: 
"""

import win32com.client
import pandas as pd
import subprocess
import os
import sys
from pathlib import Path
import re
from datetime import datetime
import shutil

# Find paths
#   Directory of file
#   Parent directory of file
base_dir = Path(__file__).resolve().parent
project_dir = base_dir.parent
if str(project_dir) not in sys.path:
    sys.path.insert(0, str(project_dir))

# Name of main calculator worksheet
WS_NAME = "Calculator"

# Set paths for files needed to run OCHRE
OLD_BLDG_DIR = os.path.join(base_dir, "HPWH All Portland Input Files")
B2_FILE = project_dir / "HPWH" / "HPWH_B2.py"
C1_PATH = project_dir / "HPWH" / "HPWH_C1.py"
C2_PATH = project_dir / "HPWH" / "HPWH_C2.py"
C3_PATH = project_dir / "HPWH" / "HPWH_C3.py"
D1_PATH = project_dir / "HPWH" / "HPWH_D1.py"
D2_PATH = project_dir / "HPWH" / "HPWH_D2.py"

# Set cells to read/write
# Makes changing cells easier if they're all in one place
sample_cell = "K35"
delete_results_cell = "N37"
delete_temp_bldg_cell = "N38"
month_cell = "N34"
week_day_end_cell = "N35"
fl_type_cell = "I6"
fl_name_cell = "I7"
t_res_cell = "K38"
fast_result_cell = "N29"
slow_result_cell = "N30"
fast_graph_cell = "R2"
slow_graph_cell = "R25"

# Start Excel
excel = win32com.client.GetActiveObject("Excel.Application")
wb = excel.ActiveWorkbook
WS = wb.Worksheets(WS_NAME)

# Choose the run ID once. RegA/RegD suffixes keep the two result sets apart.
RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")

# May need to be updated
# Different types of flex loads have different "Initial Inputs"
input_map = {
    "Heat Pump Water Heater": [
        "comp_pwr", "resist_pwr", "tank_vol", "max_water_temp",
        "min_water_temp", "cop_uef", "heat_cap",
        "resp_time", "cntrl_int"
    ],
    "Electric Resistance Water Heater": [
        "heat_ele_pwr", "tank_vol", "max_water_temp",
        "min_water_temp", "resp_time", "cntrl_int"
    ],
    "HVAC": [
        "elect_pwr", "heat_cap", "cool_cap", "min_mod",
        "max_indoor_temp", "min_indoor_temp",
        "resp_time", "cntrl_int", "bu_cap"
    ],
    "EV Charger": [
        "charge_pwr", "batt_cap", "batt_flex",
        "charge_eff", "resp_time", "cntrl_int"
    ],
    "Dryer": [
        "rated_pwr", "cycle_energy", "typ_cyc_dur",
        "max_def_time", "resp_time", "cntrl_int"
    ],
    "Battery": [
        "rated_pwr", "energy_cap", "SoC_range",
        "max_resp_time", "recovery_rate", "comm_int"
    ],
    "Generic": [
        "tot_pwr", "reg_cap", "cont_reg_dur",
        "resp_time", "recovery_time", "cntrl_int"
    ]
}

# HELPER FUNCTIONS

# DELETE t_res functions after debugging
def set_t_res(value, file):
    """Update t_res in the B2 OCHRE script."""

    value = float(value)
    text = file.read_text()

    new_text, count = re.subn(
        r"(^\s*t_res\s*=\s*)[-+]?\d*\.?\d+",
        rf"\g<1>{value}",
        text,
        count=1,
        flags=re.MULTILINE
    )

    if count == 0:
        raise ValueError(
            f"Could not find a t_res assignment in:\n{file}"
        )

    file.write_text(new_text)

def check_t_res(t_res, b2_file):
    updated_text = b2_file.read_text()

    match = re.search(
        r"^\s*t_res\s*=\s*([-+]?\d*\.?\d+)",
        updated_text,
        flags=re.MULTILINE
    )

    if match is None:
        raise RuntimeError("t_res could not be verified in the B2 file.")

    updated_t_res = float(match.group(1))

    if updated_t_res != float(t_res):
        raise RuntimeError(
            f"t_res update failed. "
            f"Excel value = {t_res}, B2 value = {updated_t_res}"
        )

# Start of good helper functions
def set_reg_type(value, file):
    """Update REG_TYPE in the B2 OCHRE script."""

    text = file.read_text()

    new_text, count = re.subn(
        r'(^\s*REG_TYPE\s*=\s*)["\'].*?["\']',
        lambda match: match.group(1) + repr(str(value)),
        text,
        count=1,
        flags=re.MULTILINE
    )

    if count == 0:
        raise ValueError(
            f"Could not find a REG_TYPE assignment in:\n{file}"
        )

    file.write_text(new_text)


def check_reg_type(reg_type, b2_file):
    # Check that the REG_TYPE parameter was updated in B2
    updated_text = b2_file.read_text()

    if not re.search(
        rf'^\s*REG_TYPE\s*=\s*["\']{re.escape(str(reg_type))}["\']',
        updated_text,
        flags=re.MULTILINE
    ):
        raise RuntimeError("REG_TYPE could not be verified in the B2 file.")


def delete_old_graphs():
    """Delete graphs inserted by this script, including legacy image names."""

    graph_names = (
        "HPWH RegA Regulation Graph",
        "HPWH REgD Regulation Graph",
    )

    for graph_name in graph_names:
        try:
            WS.Shapes.Item(graph_name).Delete()
        except Exception:
            # Excel raises a COM error when a shape with this name is absent.
            pass


def print_graph(cell, reg_type):
    # Put the graph from C3 in Excel
    run_id = f"{RUN_ID}_{reg_type}"
    image_path = (
            project_dir
            / "HPWH"
            / "Ready_data"
            / run_id
            / f"{run_id}_normalized_power_plot.png"
        )
    
    if not image_path.is_file():
        raise FileNotFoundError(f"Plot image was not created: {image_path}")
    
    anchor = WS.Range(cell)
    
    picture = WS.Shapes.AddPicture(
        str(image_path.resolve()),
        False,  # LinkToFile
        True,   # SaveWithDocument
        anchor.Left,
        anchor.Top,
        -1,     # Preserve original width
        -1      # Preserve original height
    )
    picture.Name = f"HPWH {reg_type} Regulation Graph"
    
    # Optional resizing:
    picture.LockAspectRatio = True
    picture.Width = 600
    picture.Height = 350


def run_files(params, reg_type):
    # Run the different files needed to run OCHRE
    from HPWH import HPWH_B2 as run_ochre
    run_id = f"{RUN_ID}_{reg_type}"
    run_ochre.main(params, run_id=run_id)
    subprocess.run([sys.executable, str(C1_PATH), "--run-id", run_id], check=True)
    subprocess.run([sys.executable, str(C2_PATH), "--run-id", run_id], check=True)
    subprocess.run([sys.executable, str(C3_PATH), "--run-id", run_id], check=True)
    from HPWH import HPWH_C4 as pjm_scores
    return pjm_scores.main(run_id)


def set_run_ochre(params, reg_type, result_cell, graph_cell):
    # Setup and run OCHRE
    set_reg_type(reg_type, B2_FILE)
    check_reg_type(reg_type, B2_FILE)
    WS.Range(result_cell).Value = run_files(params, reg_type)
    print_graph(graph_cell, reg_type)


def main():
    # Cleanup
    if WS.Range(delete_results_cell).Value == "Yes":
        subprocess.run([sys.executable, str(D1_PATH)], check=True)

    delete_old_graphs()

    # future use variables
    month = WS.Range(month_cell).Value
    week_day_end = WS.Range(week_day_end_cell).Value
    sample = WS.Range(sample_cell)
    FL_name = WS.Range(fl_name_cell).Value

    # Get type of flex load
    FL_type = WS.Range(fl_type_cell).Value
    if FL_type not in input_map:
        raise ValueError(f"Unsupported flex load type: {FL_type}")
    # Get parameters of flex load
    params = {
        var: WS.Range(f"K{i}").value
        for i, var in enumerate(input_map[FL_type], start=9)
    }

    # Update t_res - REMOVE (debugging)
    t_res = WS.Range(t_res_cell).Value
    set_t_res(t_res, B2_FILE)
    check_t_res(t_res, B2_FILE)

    # Update XML of flex load with calculator parameterss
    from HPWH import HPWH_A3 as adj_xml
    adj_xml.main(params)
    # Run OCHRE
    set_run_ochre(params, "RegA", slow_result_cell, slow_graph_cell)
    set_run_ochre(params, "RegD", fast_result_cell, fast_graph_cell)

    # Cleanup
    subprocess.run([sys.executable, str(D1_PATH)], check=True)

    excel.Calculate()


if __name__ == "__main__":
    main()
