import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import pandas as pd


REG_DIR = Path(__file__).resolve().parent
INPUT_PATH = REG_DIR / "ancillary-services-frequency.csv"
OUTPUT_DIR = REG_DIR.parent / "OCHRE in Excel" / "Reg Sig"
OUTPUT_PATH_A = OUTPUT_DIR / "RegA-ochre.csv"
OUTPUT_PATH_D = OUTPUT_DIR / "RegD-ochre.csv"

def load_ace(path):
    """Load the headerless time/frequency file and determine its cadence."""
    raw = pd.read_csv(path)

    raw["DateTime"] = pd.to_timedelta(
        raw["DateTime"].astype(str).str[11:],
        errors="raise",
    )
    raw["Frequency"] = pd.to_numeric(raw["Frequency"], errors="raise")

    if len(raw) < 2:
        raise ValueError("The ACE input must contain at least two samples.")

    time_steps = raw["DateTime"].diff().dropna().dt.total_seconds()
    if (time_steps <= 0).any() or not np.allclose(time_steps, time_steps.iloc[0]):
        raise ValueError("Input timestamps must be strictly increasing and evenly spaced.")

    return raw["Frequency"], raw["DateTime"], float(time_steps.iloc[0])


signal, time, sample_seconds = load_ace(INPUT_PATH)

N = len(signal)

# Compute a one-sided FFT of the variation around the mean frequency. Removing
# the approximately 60 Hz DC component keeps it from overwhelming the much
# smaller frequency fluctuations that we want to inspect.
frequency_deviation = signal.to_numpy() - signal.mean()
fft_output = np.fft.rfft(frequency_deviation)
frequencies = np.fft.rfftfreq(N, d=sample_seconds)

# Convert to a one-sided amplitude spectrum.
magnitudes = np.abs(fft_output) / N
if N % 2 == 0:
    magnitudes[1:-1] *= 2
else:
    magnitudes[1:] *= 2

find_median = []

for i in range(len(frequencies)):
    for j in range(int(magnitudes[i] * 100000)):
        find_median.append(frequencies[i])

freq_med = np.median(find_median)
print(freq_med)

# 5. Plot the results
plt.figure(figsize=(12, 5))

# Time Domain Plot
plt.subplot(1, 2, 1)
plt.plot(time[:200], signal[:200], color='blue')  # Show first 200 samples for clarity
plt.title("Time Domain (Original Signal)")
plt.xlabel("Time (seconds)")
plt.ylabel("Amplitude")
plt.grid(True)

# Frequency Domain Plot
plt.subplot(1, 2, 2)
plt.plot(frequencies[1:], magnitudes[1:], color='red', linewidth=1.5)
plt.axvline(freq_med)
plt.title("Frequency Domain (FFT)")
plt.xlabel("Frequency (Hz)")
plt.ylabel("Magnitude")
plt.xlim(0, frequencies[-1])  # Nyquist limit for the detected sample cadence
plt.grid(True)

plt.tight_layout()
plt.show()
