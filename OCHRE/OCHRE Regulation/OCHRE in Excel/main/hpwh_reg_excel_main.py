import win32com.client
import pandas as pd
import subprocess
import os
import sys
from pathlib import Path

base_dir = Path(__file__).resolve().parent
project_dir = base_dir.parent
if str(project_dir) not in sys.path:
    sys.path.insert(0, str(project_dir))

from HPWH import HPWH_A3_adjustXML as adj_xml
from HPWH import HPWH_B2_EnergySched_LoadShaping as run_ochre
from HPWH import HPWH_C3_Plot_norm_pwr as get_reg



# get type of fl
# get parameters for fl
# get parameters for ochre
#   Population, adoption rate, start/stop time, timestep, dr participation?, % reachable?, path to reg sig or select rega or regd
# send parameters to A3
# run A3
# run B2
# run C1
# run C2
# run C3
# send correlation from c3 to excel

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

excel = win32com.client.GetActiveObject("Excel.Application")
wb = excel.ActiveWorkbook

inputs = wb.Worksheets("Calculator")

start_time = inputs.Range("N36").Value
end_time = inputs.Range("N37").Value
month_load_amt = inputs.Range("M33").Value

t_res = inputs.Range("N39").Value

pop_num = inputs.Range("K35").Value
adopt_rate = inputs.Range("K37").Value

FL_type = inputs.Range("I6").Value
if FL_type not in input_map:
    raise ValueError(f"Unsupported flex load type: {FL_type}")

FL_name = inputs.Range("I7").Value

params = {
    var: inputs.Range(f"K{i}").value
    for i, var in enumerate(input_map[FL_type], start=9)
}

if FL_type == "Heat Pump Water Heater":
    # subprocess.run(['python', "HPWH_Reg_A1_recreate_oregon_filters.py"], check=True)
    # subprocess.run(['python', "HPWH_Reg_A2_downloadTestSet.py"], check=True)
    adj_xml.main(params)
    # subprocess.run(['python', "HPWH_Reg_A4_make_reg_signal.py"], check=True)
    run_ochre.main(params)
    subprocess.run([sys.executable, str(hpwh_dir / "HPWH_C1_parse_OCHRE_data_final.py")], check=True)
    subprocess.run([sys.executable, str(hpwh_dir / "HPWH_C2_Plot_Totpower_WHpower.py")], check=True)
    reg_corr = get_reg.main()


inputs.Range("N29").Value = reg_corr

excel.Calculate()
