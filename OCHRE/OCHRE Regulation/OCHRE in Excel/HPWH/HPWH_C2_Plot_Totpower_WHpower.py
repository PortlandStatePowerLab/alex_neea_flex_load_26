"""
#Author: Thomas Metzler
#6/22/2026

#Creates plots for the average water heater and total household power consumption, comparing baseline and controlled
#Works for HPWH 

Modified by Alex Wardwell
Modified on 8/19/26
"""


import argparse

import pandas as pd
import os
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import matplotlib.dates as mdates

import warnings

warnings.filterwarnings("ignore")


#Copy path naming from HPWH_parse_OCHRE_data_final.py for consistency
script_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.dirname(script_dir)
# working_dir = os.path.dirname(project_dir)  

reg_sig_file = os.path.join(project_dir, "Reg Sig", "rega_filtered.csv")

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

#plot the data and save the plot
def plot_data(baseline_file, controlled_file, title, photo_file, ax):
    # Load the CSV file
    df_base = pd.read_csv(baseline_file, index_col=0)  # Assuming the first column is the index
    df_con= pd.read_csv(controlled_file, index_col=0)  # Assuming the first column is the index

    # Extract the first row (index 0) and last row (index -1)
    # .iloc[[0, -1]] selects both rows into a new DataFrame
    subset_df_base = df_base.iloc[[0, -1]]
    subset_df_con = df_con.iloc[[0, -1]]

    #transpose data to have time as columns and power as rows
    transposed_df_base = subset_df_base.iloc[1,:]
    transposed_df_con = subset_df_con.iloc[1,:]
    
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
    df_base['Time'] = pd.to_datetime(df_base['Time'], errors='coerce').dt.strftime('%H:%M')
    df_con['Time'] = pd.to_datetime(df_con['Time'], errors='coerce').dt.strftime('%H:%M')

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
    
    plt.savefig(photo_file, dpi=300, bbox_inches='tight')

def main(run_id):
    folder_path = os.path.join(script_dir, "Ready_data", run_id)
    output_file_1 = os.path.join(folder_path, f"{run_id}_baseline_WH_power.csv")
    output_file_2 = os.path.join(folder_path, f"{run_id}_controlled_WH_power.csv")
    output_file_3 = os.path.join(folder_path, f"{run_id}_baseline_total_power.csv")
    output_file_4 = os.path.join(folder_path, f"{run_id}_controlled_total_power.csv")
    photo_file_1 = os.path.join(folder_path, f"{run_id}_WH_power_plot.png")
    photo_file_2 = os.path.join(folder_path, f"{run_id}_Total_power_plot.png")

    save_avg(output_file_1)
    save_avg(output_file_2)
    plot_data(output_file_1, output_file_2, 'Average Power Consumption per Water Heater', photo_file_1, "ax1")

    save_avg(output_file_3)
    save_avg(output_file_4)
    plot_data(output_file_3, output_file_4, 'Average Total Power Consumption per Household', photo_file_2, "ax2")

    # Show plots after both have been saved.
    # plt.show()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    main(parser.parse_args().run_id)

