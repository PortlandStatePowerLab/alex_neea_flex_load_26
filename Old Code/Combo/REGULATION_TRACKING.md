# Sinusoidal regulation tracking

Run B1 and B2 as before. Each controlled run remains in its own subfolder of
its baseline. B2 now writes `tracking_summary.json` alongside the tracking CSV.

## Controller changes

- Pending commands count toward predicted power only at their activation timestep.
  `pending_delta_kw` now means due-now power; `future_pending_delta_kw` reports
  the remainder. `predicted_current_delta_kw` includes new immediate dispatch.
- Thermal dispatch predicts the request at activation using a clipped linear
  extrapolation of the current and previous signal samples. It never reads future
  sine samples. Set `CAUSAL_LOOKAHEAD=False` to compare persistence prediction.
- Candidates prioritize response speed, closeness to the required power change,
  available thermal temperature margin, then usage count. Physical eligibility
  and OCHRE minimum run/off times still apply.
- The controller thermal hold defaults to one minute instead of five. This
  changes the command hold only; modeled equipment cycling limits remain.
- Zero-delay batteries use continuous AC power setpoints. Zero-delay EVs use
  continuous charging ceilings. Physical power, SOC/energy, event boundaries,
  and configured LU/S limits constrain these commands. Equipment with a nonzero
  modeled response delay retains queued mode dispatch. Explicit safety modes
  take priority. Set `CONTINUOUS_POWER_CONTROL=False` for discrete comparisons.
- `REGULATION_CAPACITY_FRACTION` scales both B1 capacities for the B2 commitment.
  Default 1.0 preserves the full reported commitment; use .5 or .75 to test
  lower commitments. The controlled manifest records the fraction and committed
  capacities, and the tracking CSV/scoring use those committed capacities.
- `FEEDBACK_GAIN` remains .8 pending comparison evidence. The normal timestep
  remains one minute so existing baselines stay usable.

## Parameter comparison

From the repository root:

```powershell
python Combo/E2_TrackingTuning.py --frequency .1
```

This runs 18 controlled trials: three capacity fractions (.5, .75, 1), three
feedback gains (.6, .8, 1), and two timesteps (1 and .5 minutes). It creates
one fresh B1 baseline per timestep. All controlled trials are saved under that
baseline in `Combo/Results/TrackingTuning/<comparison>/timestep_<step>/`.
`comparison.csv` and `comparison.json` checkpoint after each trial. A failed
trial records its error and stops the comparison. Original in-memory settings
are restored when the comparison exits.

A smaller first comparison:

```powershell
python Combo/E2_TrackingTuning.py --frequency .1 --fractions .75 1 --gains .8 1 --timesteps 1
```

Use `--timesteps .5` to test 30-second simulation and dispatch, with a fresh
matching baseline. Changing B2's timestep alone cannot reuse a one-minute B1
baseline. Finer timesteps increase simulation and scoring cost.

Diagnostics include tracking RMSE/MAE in kW, zero-lag correlation, actual/target
RMS ratio, through-origin response gain, and best correlation and lag. Positive
lag means actual response trails target. The lag search is restricted to ten
minutes and half the record; periodic signals can have ambiguous lag peaks.
The original time series is never shifted for RMSE or PJM-style scoring.
Compare normalized error as well as absolute kW error across capacity fractions:
a smaller commitment naturally reduces absolute tracking error. Improvements
must be verified on actual fleet runs; unit tests do not establish fleet scores.

## Energy-aware dispatch and early-day capacity dips

`ENERGY_AWARE_DISPATCH=True` prioritizes thermal temperature margin before
power fit and shares continuous EV/battery power using directional remaining
energy. This avoids filling the first devices in fleet order. Battery commands
prefer recovery toward the midpoint of their physical SOC bounds over
`ENERGY_RECOVERY_HOURS` (default 2 hours). Other continuous devices offset that
recovery within the same aggregate tracking request. Recovery is best effort:
physical bounds and the fleet target take priority, and an explicit gross ramp
budget disables counteracting recovery when needed. EV charging remains bounded
by the current charging event; departure-energy scheduling is not implemented.
Thermal devices retain their existing command releases and physical cycling
limits. No extra off-target thermal recovery load is introduced.

Tracking CSVs now include per-device available up/down kW and estimated dispatched
delta kW. These are instantaneous command estimates, not measured delivered
response. Existing per-home controlled exports provide power and EV/battery SOC.

The default `REGULATION_CAPACITY_MODE="asymmetric"` preserves B1's directional
capacities. To test equal positive/negative kW amplitudes using the smaller B1
capacity in both directions, reuse a completed baseline:

```powershell
python Combo/B2_Regulation.py --baseline-run-id 20261030_092345_2a144abd --sine-freq .1 --capacity-mode symmetric
```

This changes the committed service and its normalization; it is a separate
comparison, not evidence of improvement at the original commitment. Asymmetric
capacities turn a zero-mean sine into a nonzero-mean kW request, so energy-aware
allocation cannot guarantee sustained tracking when the fleet runs out of energy
margin. Compare both modes and `ENERGY_AWARE_DISPATCH=False` using the same
baseline and signal. Full fleet runs are required to quantify improvements.
