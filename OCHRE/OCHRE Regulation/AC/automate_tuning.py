import subprocess
import importlib

TARGET = 0.85
TOL = 0.01

capacity = 0.25
step = 0.05

import re

def set_regulation_capacity(value):

    with open("AC_B2_EnergySched_LoadShaping","r") as f:
        text = f.read()

    text = re.sub(
        r"(regulation_capacity\s*=\s*)[-0-9.]+",
        rf"\g<1>{value}",
        text
    )

    with open("AC_B2_EnergySched_LoadShaping","w") as f:
        f.write(text)

while True:

    # ------------------------
    # Modify AC_B2 input
    # ------------------------
    set_regulation_capacity(capacity)

    # ------------------------
    # Run the simulation
    # ------------------------
    subprocess.run(
        ["python", "AC_B2_EnergySched_LoadShaping"],
        check=True
    )

    subprocess.run(
        ["python", "AC_C1_parse_OCHRE_data_final.py"],
        check=True
    )

    subprocess.run(
        ["python", "AC_C2_Plot_Totpower_WHpower copy.py"],
        check=True
    )

    # ------------------------
    # Compute correlation
    # ------------------------
    import AC_C3_Plot_norm_pwr as c3
    importlib.reload(c3)

    corr = c3.calculate_correlation()

    print(capacity, corr)

    if abs(corr - TARGET) < TOL:
        break

    if corr < TARGET:
        capacity += step
    else:
        capacity -= step
        step /= 2