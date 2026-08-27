import numpy as np
import datetime as dt
import pandas as pd
from scipy.fft import fft, fftfreq

Start = dt.datetime(2018, 1, 11, 0, 0)
Duration = 1  # days
t_res = 1.0  # minutes

duration_min = Duration * 24 * 60
frequency = f"{t_res}min"
period = int(duration_min / t_res)
sim_times = pd.date_range(start=Start, periods=period, freq=frequency)
x = np.arange(0, 1440*0.1, 0.1)
REG_SIGNAL = pd.Series(
    np.sin(x),
    index=sim_times
)

# import matplotlib.pyplot as plt
# plt.plot(sim_times[-100:], np.sin(x)[-100:], color='green')
# plt.show()

print(find_sine_frequency(REG_SIGNAL, 0.1))