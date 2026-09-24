"""
#Author: Thomas Metzler
#6/22/2026

#Creates plots for the average water heater and total household power consumption, comparing baseline and controlled
#Works for HPWH 
"""


import pandas as pd
import os
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import matplotlib.dates as mdates
import datetime as dt


script_dir = os.path.dirname(os.path.abspath(__file__))
fl_dir = os.path.dirname(script_dir)
working_dir = os.path.dirname(fl_dir)   

input_file_root = 'Combo_WH_HVAC_Dryer_EV_Battery_TEST_3'

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


input_file_name_base = input_file_root + "_baseline"
input_file_name_ctrl = input_file_root + "_controlled"
input_file_base  = os.path.join(working_dir, input_file_name_base +".csv")
input_file_ctrl  = os.path.join(working_dir, input_file_name_ctrl +".csv")

folder_path = os.path.join(working_dir, "Ready_data", input_file_root)

if WH_SIMULATION == "ON":
    output_append_WHpower = "_WH_power"
    output_file_name_base_WH = input_file_name_base + output_append_WHpower + ".csv"
    output_file_name_ctrl_WH = input_file_name_ctrl + output_append_WHpower + ".csv"
    output_file_base_WH = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_base_WH)
    output_file_ctrl_WH = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_ctrl_WH)

if HVAC_SIMULATION == "ON":
    output_append_ACpower = "_AC_power"
    output_file_name_base_AC = input_file_name_base + output_append_ACpower + ".csv"
    output_file_name_ctrl_AC = input_file_name_ctrl + output_append_ACpower + ".csv"
    output_file_base_AC = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_base_AC)
    output_file_ctrl_AC = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_ctrl_AC)

    output_append_HEATpower = "_HEAT_power"
    output_file_name_base_HEAT = input_file_name_base + output_append_HEATpower + ".csv"
    output_file_name_ctrl_HEAT = input_file_name_ctrl + output_append_HEATpower + ".csv"
    output_file_base_HEAT = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_base_HEAT)
    output_file_ctrl_HEAT = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_ctrl_HEAT)

if DRYER_SIMULATION == "ON":
    output_append_Dryerpower = "_Dryer_power"
    output_file_name_base_Dryer = input_file_name_base + output_append_Dryerpower + ".csv"
    output_file_name_ctrl_Dryer = input_file_name_ctrl + output_append_Dryerpower + ".csv"
    output_file_base_Dryer = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_base_Dryer)
    output_file_ctrl_Dryer = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_ctrl_Dryer)

if EV_SIMULATION == "ON":
    output_append_EVpower = "_EV_power"
    output_file_name_base_EV = input_file_name_base + output_append_EVpower + ".csv"
    output_file_name_ctrl_EV = input_file_name_ctrl + output_append_EVpower + ".csv"
    output_file_base_EV = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_base_EV)
    output_file_ctrl_EV = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_ctrl_EV)

    output_append_EVSOC = "_EV_SOC"
    output_file_name_base_EVSOC = input_file_name_base + output_append_EVSOC + ".csv"
    output_file_name_ctrl_EVSOC = input_file_name_ctrl + output_append_EVSOC + ".csv"
    output_file_base_EVSOC = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_base_EVSOC)
    output_file_ctrl_EVSOC = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_ctrl_EVSOC)

if BATTERY_SIMULATION == "ON":
    output_append_BATTpower = "_BATT_power"
    output_file_name_base_BATT = input_file_name_base + output_append_BATTpower + ".csv"
    output_file_name_ctrl_BATT = input_file_name_ctrl + output_append_BATTpower + ".csv"
    output_file_base_BATT = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_base_BATT)
    output_file_ctrl_BATT = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_ctrl_BATT)

    output_append_BATTSOC = "_BATT_SOC"
    output_file_name_base_BATTSOC = input_file_name_base + output_append_BATTSOC + ".csv"
    output_file_name_ctrl_BATTSOC = input_file_name_ctrl + output_append_BATTSOC + ".csv"
    output_file_base_BATTSOC = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_base_BATTSOC)
    output_file_ctrl_BATTSOC = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_ctrl_BATTSOC)

output_append_totpower = "_total_power"
output_file_name_base_total = input_file_name_base + output_append_totpower + ".csv"
output_file_name_ctrl_total = input_file_name_ctrl + output_append_totpower + ".csv"
output_file_base_total = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_base_total)
output_file_ctrl_total = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name_ctrl_total)


photo_file_WH = os.path.join(working_dir, "Ready_data", input_file_root, input_file_root + "_WH_power_plot.png")
photo_file_AC = os.path.join(working_dir, "Ready_data", input_file_root, input_file_root + "_AC_power_plot.png")
photo_file_HEAT = os.path.join(working_dir, "Ready_data", input_file_root, input_file_root + "_HEAT_power_plot.png")
photo_file_Dryer = os.path.join(working_dir, "Ready_data", input_file_root, input_file_root + "_Dryer_power_plot.png")
photo_file_EV = os.path.join(working_dir, "Ready_data", input_file_root, input_file_root + "_EV_power_plot.png")
photo_file_EVSOC = os.path.join(working_dir, "Ready_data", input_file_root, input_file_root + "_EV_SOC_plot.png")
photo_file_BATT = os.path.join(working_dir, "Ready_data", input_file_root, input_file_root + "_BATT_power_plot.png")
photo_file_BATTSOC = os.path.join(working_dir, "Ready_data", input_file_root, input_file_root + "_BATT_SOC_plot.png")
photo_file_total = os.path.join(working_dir, "Ready_data", input_file_root, input_file_root + "_total_power_plot.png")


#Saves the average of each column as a new row
def save_avg(file):
    # 1. Read the CSV file into a DataFrame
    df = pd.read_csv(file)

    # 2. Calculate the mean for numeric columns
    averages = df.mean(numeric_only=True)

    # 3. Append the averages as a new row (using 'Average' as the row label/index)
    df.loc['Average'] = averages

    # 4. Save back to a CSV file
    df.to_csv(file, index=False)

def get_active_commands():
    schedule_file = os.path.join(script_dir, "B0_Commands_Schedule.csv")
    commands = []
    try:
        df_sched = pd.read_csv(schedule_file)
        for _, row in df_sched.iterrows():
            if str(row['OnOff']).strip().upper() == 'ON':
                cmd_name = str(row['Command']).strip()
                
                # Calculate trapezoid time coordinates
                t0 = pd.to_datetime(str(row['START RAMP IN']).strip(), format='%H:%M')
                t1 = t0 + pd.Timedelta(hours=float(row['DURATION RAMP IN']))
                t2 = pd.to_datetime(str(row['START RAMP OUT']).strip(), format='%H:%M')
                t3 = t2 + pd.Timedelta(hours=float(row['DURATION RAMP OUT']))
                
                # --- DEBUG PRINT ---
                print(f"[{cmd_name}] Ramp In: {t0.strftime('%H:%M')} to {t1.strftime('%H:%M')} | Ramp Out: {t2.strftime('%H:%M')} to {t3.strftime('%H:%M')}")
                
                # Assign colors and labels based on the command type
                if 'ALU' in cmd_name:
                    c_type, color = 'Advanced Load Up', "#00FF087C"
                elif 'LU' in cmd_name:
                    c_type, color = 'Load Up', "#0077FF85"
                elif 'CP' in cmd_name:
                    c_type, color = 'Critical Peak', "#FF660083"
                elif 'GE' in cmd_name:
                    c_type, color = 'Grid Emergency', "#FF00008F"
                elif 'S' in cmd_name:
                    c_type, color = 'Shed', "#FF00DD8D"
                else:
                    c_type, color = 'Other', '#9E9E9E'
                    
                commands.append({'type': c_type, 'color': color, 'times': [t0, t1, t2, t3]})
    except FileNotFoundError:
        print(f"[WARNING] Schedule file not found.")
    return commands

#plot the data and save the plot
def plot_data(baseline_file, controlled_file, title, photo_file, schedule_commands):
    df_base = pd.read_csv(baseline_file, index_col=0)
    df_con = pd.read_csv(controlled_file, index_col=0)

    # Extract averages and transpose (Keeping your existing logic)
    df_base = pd.DataFrame(df_base.iloc[[0, -1]].iloc[1, :]).reset_index()
    df_con = pd.DataFrame(df_con.iloc[[0, -1]].iloc[1, :]).reset_index()
    
    df_base.columns = ['Time', 'baseline']
    df_con.columns = ['Time', 'controlled']

    # Convert to actual datetime objects for smooth plotting
    df_base['Time'] = pd.to_datetime(df_base['Time'], format='%H:%M', errors='coerce')
    df_con['Time'] = pd.to_datetime(df_con['Time'], format='%H:%M', errors='coerce')

    fig, ax1 = plt.subplots(figsize=(10, 5))

    # --- PRIMARY AXIS: Power ---
    ax1.plot(df_base['Time'], df_base['baseline'], label='Baseline', color='#004C6D', linewidth=2)
    ax1.plot(df_con['Time'], df_con['controlled'], label='Controlled', color='#E26D28', linewidth=2)
    ax1.set_ylabel('Power (kW)')
    ax1.set_title(title)
    ax1.grid(True, alpha=0.3)

    # --- SECONDARY AXIS: Command Ramping ---
    ax2 = ax1.twinx()
    ax2.set_ylabel('Fraction of units given command')
    ax2.set_ylim(0, 1)
    
    added_labels = set()
    for cmd in schedule_commands:
        y_vals = [0, 1, 1, 0] # Trapezoid height
        label = cmd['type'] if cmd['type'] not in added_labels else ""
        if label: added_labels.add(label)
            
        ax2.plot(cmd['times'], y_vals, color=cmd['color'], linewidth=1)
        ax2.fill_between(cmd['times'], y_vals, color=cmd['color'], alpha=0.1, label=label)

    # --- FORMATTING & LEGEND ---
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax1.xaxis.set_major_locator(mdates.HourLocator(interval=2))
    plt.setp(ax1.get_xticklabels(), rotation=45)

    # Combine legends from both axes at the bottom
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper center', bbox_to_anchor=(0.5, -0.2), ncol=4, frameon=False)

    plt.tight_layout()
    plt.savefig(photo_file, dpi=300, bbox_inches='tight')
    plt.close()


active_commands = get_active_commands()

if WH_SIMULATION == "ON":
    save_avg(output_file_base_WH)
    save_avg(output_file_ctrl_WH)
    plot_data(output_file_base_WH, output_file_ctrl_WH, 'Average Power Consumption per Water Heater', photo_file_WH, active_commands)

if HVAC_SIMULATION == "ON":
    save_avg(output_file_base_AC)
    save_avg(output_file_ctrl_AC)
    plot_data(output_file_base_AC, output_file_ctrl_AC, 'Average Power Consumption per AC System', photo_file_AC, active_commands)
    save_avg(output_file_base_HEAT)
    save_avg(output_file_ctrl_HEAT)
    plot_data(output_file_base_HEAT, output_file_ctrl_HEAT, 'Average Power Consumption per Heating System', photo_file_HEAT, active_commands)

if DRYER_SIMULATION == "ON":
    save_avg(output_file_base_Dryer)
    save_avg(output_file_ctrl_Dryer)
    plot_data(output_file_base_Dryer, output_file_ctrl_Dryer, 'Average Power Consumption per Dryer', photo_file_Dryer, active_commands)

if EV_SIMULATION == "ON":
    save_avg(output_file_base_EV)
    save_avg(output_file_ctrl_EV)
    plot_data(output_file_base_EV, output_file_ctrl_EV, 'Average Power Consumption per Electric Vehicle', photo_file_EV, active_commands)
    save_avg(output_file_base_EVSOC)
    save_avg(output_file_ctrl_EVSOC)
    plot_data(output_file_base_EVSOC, output_file_ctrl_EVSOC, 'Average State of Charge per Electric Vehicle', photo_file_EVSOC, active_commands)

if BATTERY_SIMULATION == "ON":
    save_avg(output_file_base_BATT)
    save_avg(output_file_ctrl_BATT)
    plot_data(output_file_base_BATT, output_file_ctrl_BATT, 'Average Power Consumption per Battery', photo_file_BATT, active_commands)
    save_avg(output_file_base_BATTSOC)
    save_avg(output_file_ctrl_BATTSOC)
    plot_data(output_file_base_BATTSOC, output_file_ctrl_BATTSOC, 'Average State of Charge per Battery', photo_file_BATTSOC, active_commands)

save_avg(output_file_base_total)
save_avg(output_file_ctrl_total)
plot_data(output_file_base_total, output_file_ctrl_total, 'Average Total Power Consumption per Household', photo_file_total, active_commands)

#Show plot at the end so it doesn't overwrite the previous plot
plt.show()

