import subprocess
import sys
import re
from pathlib import Path

import AC_C3_Plot_norm_pwr as c3

# --------------------------------------------------
# Settings
# --------------------------------------------------

TARGET = 0.85
TOL = 0.01

MAX_ITERATIONS = 50

BASE = Path(
    r"C:\Users\Documents\GitHub\alex_neea_flex_load_26\OCHRE\OCHRE Regulation\AC"
)

capacity = 25.0
step = 25.0

history = []

# --------------------------------------------------
# Helper Functions
# --------------------------------------------------

def set_regulation_capacity(value):
    """Modify REGULATION_CAPACITY_KW in AC_B2_EnergySched_LoadShaping.py"""

    file = BASE / "AC_B2_EnergySched_LoadShaping.py"

    text = file.read_text()

    text = re.sub(
        r"(REGULATION_CAPACITY_KW\s*=\s*)[-0-9.]+",
        rf"\g<1>{value}",
        text,
    )

    file.write_text(text)


def run_script(filename):
    """Run a Python script using the current Python interpreter."""

    script = BASE / filename

    print(f"\nRunning {filename}...")

    subprocess.run(
        [sys.executable, str(script)],
        cwd=BASE,
        check=True,
    )


# --------------------------------------------------
# Optimization Loop
# --------------------------------------------------

for iteration in range(MAX_ITERATIONS):

    print(f"\nIteration {iteration + 1}")
    print(f"\nTrying regulation capacity = {capacity:.3f} kW")

    # Modify B2 input file
    set_regulation_capacity(capacity)

    # Run simulation
    run_script("AC_B2_EnergySched_LoadShaping.py")
    run_script("AC_C1_parse_OCHRE_data_final.py")
    run_script("AC_C2_Plot_Totpower_WHpower copy.py")

    # Calculate correlation
    corr = c3.calculate_correlation()

    history.append((capacity, corr))

    print("\nHistory:")
    for cap, c in history:
        print(f"  {cap:7.2f} kW -> {c:.4f}")

    print(f"Correlation = {corr:.4f}")

    # Check convergence
    if abs(corr - TARGET) <= TOL:
        print("\nTarget reached!")
        print(f"Best regulation capacity = {capacity:.3f} kW")
        print(f"Correlation = {corr:.4f}")
        break

    # Adjust capacity
    if corr < TARGET:
        capacity += step
    else:
        capacity -= step
        step /= 2

        # Prevent step from becoming effectively zero
        if step < 0.01:
            print("\nStep size became too small.")
            break

else:
    print("Reached maximum number of iterations.")