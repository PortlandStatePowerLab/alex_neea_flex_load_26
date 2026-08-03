import subprocess
import importlib
import os

print(os.getcwd())
print(os.listdir())

TARGET = 0.85
TOL = 0.01

capacity = 25
step = 25

import re

def set_regulation_capacity(value):

    from pathlib import Path

    file = Path(__file__).parent / "AC_B2_EnergySched_LoadShaping.py"

    with file.open("r") as f:
        text = f.read()

    text = re.sub(
        r"(REGULATION_CAPACITY_KW\s*=\s*)[-0-9.]+",
        rf"\g<1>{value}",
        text
    )

    with file.open("w") as f:
        f.write(text)

# while True:

#     # ------------------------
#     # Modify AC_B2 input
#     # ------------------------
#     set_regulation_capacity(capacity)

#     # ------------------------
#     # Run the simulation
#     # ------------------------
#     subprocess.run(
#         ["python", "AC_B2_EnergySched_LoadShaping"],
#         check=True
#     )

#     subprocess.run(
#         ["python", "AC_C1_parse_OCHRE_data_final.py"],
#         check=True
#     )

#     subprocess.run(
#         ["python", "AC_C2_Plot_Totpower_WHpower copy.py"],
#         check=True
#     )

#     # ------------------------
#     # Compute correlation
#     # ------------------------
#     import AC_C3_Plot_norm_pwr as c3
#     importlib.reload(c3)

#     corr = c3.calculate_correlation()

#     print(capacity, corr)

#     if abs(corr - TARGET) < TOL:
#         break

#     if corr < TARGET:
#         capacity += step
#     else:
#         capacity -= step
#         step /= 2

set_regulation_capacity(capacity)