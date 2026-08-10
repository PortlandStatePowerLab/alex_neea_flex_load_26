import win32com.client
import pandas as pd
import subprocess

import Regulation.HPWH.HPWH_Reg_A3_adjustXML as adj_xml
# import Regulation.HPWH.HPWH_Reg_B1_EnergySched_OffsetSched as run_ochre
import Regulation.HPWH.HPWH_Reg_C3_get_power_vals as get_reg

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
    "Generic": [
        "tot_pwr", "reg_cap", "cont_reg_dur",
        "resp_time", "recovery_time", "cntrl_int"
    ]
}

excel = win32com.client.GetActiveObject("Excel.Application")
wb = excel.ActiveWorkbook

inputs = wb.Worksheets("Calculator")

start_time = inputs.Range("M20").Value
end_time = inputs.Range("M21").Value
start_date = inputs.Range("L20").Value
end_date = inputs.Range("L21").Value

start_datetime = f"{start_date} {start_time}"
end_datetime = f"{end_date} {end_time}"

Start = pd.to_datetime(start_datetime)
End = pd.to_datetime(end_datetime)

duration_dt = pd.to_timedelta([start_datetime, end_datetime])
Duration = (End - Start).days
t_res = inputs.Range("M23").Value

sample_num = inputs.Range("I21").Value

FL_type = inputs.Range("C4").Value
if FL_type not in input_map:
    raise ValueError(f"Unsupported flex load type: {FL_type}")

FL_name = inputs.Range("C5").Value

params = {
    var: inputs.Range(f"E{i}").value
    for i, var in enumerate(input_map[FL_type], start=7)
}

if FL_type == "Heat Pump Water Heater":
    # subprocess.run(['python', "HPWH_Reg_A1_recreate_oregon_filters.py"], check=True)
    # subprocess.run(['python', "HPWH_Reg_A2_downloadTestSet.py"], check=True)
    adj_xml.main(params)
    subprocess.run(['python', "HPWH_Reg_A4_make_reg_signal.py"], check=True)
    # run_ochre.main(Start, Duration, t_res, sample_num)
    subprocess.run(['python', "HPWH_Reg_B2_EnergySched_LoadShaping.py"], check=True)
    subprocess.run(['python', "HPWH_Reg_C1_parse_OCHRE_data_final.py"], check=True)
    subprocess.run(['python', "HPWH_Reg_C2_Plot_Totpower_WHpower.py"], check=True)
    reg_corr = get_reg.main()


inputs.Range("L15").Value = reg_corr

excel.Calculate()