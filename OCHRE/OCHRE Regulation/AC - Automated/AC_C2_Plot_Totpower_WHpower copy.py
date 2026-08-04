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
import numpy as np


#Copy path naming from HPWH_parse_OCHRE_data_final.py for consistency
script_dir = os.path.dirname(os.path.abspath(__file__))
fl_dir = os.path.dirname(script_dir) 
working_dir = os.path.dirname(fl_dir)  

# Must match ``filename`` in AC_B2_EnergySched_LoadShaping.
input_file_root = "AC_Test_PID_1.0_0.8_1.0"

input_file_name1 = input_file_root + "_baseline"
input_file_name2 = input_file_root + "_controlled"
input_file_1  = os.path.join(working_dir, input_file_name1 +".csv")
input_file_2  = os.path.join(working_dir, input_file_name2 +".csv")

output_append_ACpower = "_AC_power"
output_file_name1 = input_file_name1 + output_append_ACpower + ".csv"
output_file_name2 = input_file_name2 + output_append_ACpower + ".csv"
folder_path = os.path.join(working_dir, "Ready_data", input_file_root)
output_file_1 = os.path.join(working_dir, "Ready_data", input_file_root,output_file_name1)
output_file_2 = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name2)

output_append_totpower = "_total_power"
output_file_name3 = input_file_name1 + output_append_totpower + ".csv"
output_file_name4 = input_file_name2 + output_append_totpower + ".csv"
output_file_3 = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name3)
output_file_4 = os.path.join(working_dir, "Ready_data", input_file_root, output_file_name4)

photo_file_1 = os.path.join(working_dir, "Ready_data", input_file_root, input_file_root + "_AC_power_plot.png")
photo_file_2 = os.path.join(working_dir, "Ready_data", input_file_root, input_file_root + "_Total_power_plot.png")

# AC_B2 writes the filtered signal beside the source signal, under
# ``working_dir``.  Reading it from ``fl_dir`` used an unrelated, stale file.
reg_sig_file = os.path.join(working_dir, "RegA Signal", "rega_filtered.csv")


#plot the data and save the plot
def plot_data(baseline_file, controlled_file, title, photo_file, ax):
    # Load the CSV file
    df_base = pd.read_csv(baseline_file, index_col=0)  # Assuming the first column is the index
    df_con= pd.read_csv(controlled_file, index_col=0)  # Assuming the first column is the index

    # Each row is one home.  Average the homes directly instead of appending
    # an ``Average`` row to the input CSV on every plot run.
    transposed_df_base = df_base.mean(axis=0, numeric_only=True)
    transposed_df_con = df_con.mean(axis=0, numeric_only=True)
    
    #Switch to dataframe and reset index to have time as a column
    df_base = pd.DataFrame (transposed_df_base)
    df_con = pd.DataFrame (transposed_df_con)
    
    df_base.index = df_base.index.str.replace('Home', 'Time')
    df_con.index = df_con.index.str.replace('Home', 'Time')

    df_base = df_base.reset_index ()
    # change columns names:
    df_base.columns = ['Time', 'baseline']

    df_con = df_con.reset_index ()
    # change columns names:
    df_con.columns = ['Time', 'controlled']

    # convert time column to a usable datetime fomat
    df_reg_sig = pd.read_csv(
            reg_sig_file,
            parse_dates=["Timestamp"]
        )
    
    df_reg_sig.rename(
        columns={
            "Timestamp":"Time",
            "Signal":"signal"
        },
        inplace=True
    )
    # AC_B2 simulates a warm-up day and then retains one day of results.
    # The exported signal contains both simulation days, so keep the first
    # 24-hour signal segment instead of plotting the same clock times twice.
    signal_date = df_reg_sig['Time'].dt.normalize().iloc[0]
    df_reg_sig = df_reg_sig[
        df_reg_sig['Time'].dt.normalize() == signal_date
    ].copy()

    # convert time column to a usable datetime fomat
    for df in [df_base, df_con, df_reg_sig]:
        df['Time'] = pd.to_datetime(df['Time'])
        df['Time'] = pd.to_datetime(df['Time'].dt.strftime("1900-01-01 %H:%M:%S"))
    # df_reg_sig['Time'] = df_reg_sig['Time'].time()
    # print(df_base["Time"].min())
    # print(df_base["Time"].max())

    # print(df_reg_sig["Time"].min())
    # print(df_reg_sig["Time"].max())

    # print("Baseline:", len(df_base))
    # print("Controlled:", len(df_con))
    # print("RegA:", len(df_reg_sig))

    #plot
    fig, ax = plt.subplots(figsize=(8, 5))

    ax.plot(df_base['Time'],
            df_base['baseline'],
            label='baseline',
            color='blue')

    ax.plot(df_con['Time'],
            df_con['controlled'],
            label='controlled',
            color='orange',
            linestyle='--')

    ax2 = ax.twinx()

    ax2.plot(df_reg_sig['Time'],
            df_reg_sig['signal'],
            label='regulation signal',
            color='mediumorchid',
            linestyle=':')
    # Customize and display
    ax.set_title(title)
    ax.set_xlabel('Time')
    ax.set_ylabel('Power (kW)')
    # ax.legend() # Displays labels properly
    # ax.set_xlim(0, 24)
    # ax.set_xticks([0,6,12,18,24])
    ax2.set_ylabel("Normalized Regulation Signal")
    ax2.set_ylim(-1.1, 1.1)

    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()

    ax.legend(
        lines1 + lines2,
        labels1 + labels2,
        loc="upper right"
    )


    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=4))

    fig.autofmt_xdate()

    plt.savefig(photo_file, dpi=300, bbox_inches='tight')  # Save the figure

plot_data(output_file_1, output_file_2, 'Average AC Cooling Power per Household', photo_file_1, "ax1")
plot_data(output_file_3, output_file_4, 'Average Total Power Consumption per Household', photo_file_2, "ax2")

#Show plot at the end so it doesn't overwrite the previous plot
# plt.show()
