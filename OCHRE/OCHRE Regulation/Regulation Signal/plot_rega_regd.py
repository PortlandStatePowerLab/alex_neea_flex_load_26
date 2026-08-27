import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import pandas as pd


REG_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = REG_DIR.parent / "OCHRE in Excel" / "Reg Sig"
INPUT_PATH = OUTPUT_DIR / "RegD-ochre.csv"

def load_ace(path):
    """Load the headerless time/frequency file and determine its cadence."""
    raw = pd.read_csv(path)

    return raw["Signal"], raw["Time"]


signal, time = load_ace(INPUT_PATH)

# 5. Plot the results
plt.figure()

# Time Domain Plot
plt.plot(time[:50], signal[:50], color='blue')  # Show first 200 samples for clarity
plt.title("Time Domain (Original Signal)")
plt.xlabel("Time (seconds)")
plt.ylabel("Amplitude")
plt.grid(True)

plt.show()