"""Run a full B2 reference, then sweep 5:00-6:00 p.m. until C4 falls below 0.65.

Run: python Combo/E4_BodeSweep.py
The first complete 17:00-18:00 window in simulation time is used, with a
complete 16:30-17:00 lead-in. No best-hour selection is performed.
No existing source files are modified. Frequencies are cycles/minute. Each trial
reinitializes the fleet and replays screening prehistory, followed by 30 minutes
at its test frequency and the selected hour. This is a nonlinear, finite-window
frequency-response estimate, not an LTI system identification guarantee.
Each completed trial updates frequency_scores.csv with normalized tracking RMSE
and the selected hour's C4 precision, correlation, delay, and performance scores.
"""
import argparse
import datetime as dt
import json
from pathlib import Path
import uuid
import types

import numpy as np
import pandas as pd

THRESHOLD = 0.75
START_FREQUENCY = 0.01
FREQUENCY_STEP = 0.01
MAX_ITERATIONS = 100
LEAD_IN_MINUTES = 30


def modules():
    try:
        from . import B2_Regulation as b2, C4_Performance_Score as c4
        from . import C3_Normalized_Regulation as c3
        from .E1_SineTest import find_latest_baseline
    except ImportError:
        import B2_Regulation as b2
        import C4_Performance_Score as c4
        import C3_Normalized_Regulation as c3
        from E1_SineTest import find_latest_baseline
    return b2, c3, c4, find_latest_baseline


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, default=str, allow_nan=False), encoding='utf-8')


def fit_response(time_minutes, signal, response, frequency):
    """Fit fundamental plus DC; phase is output minus input, wrapped to +/-180."""
    t = np.asarray(time_minutes, dtype=float)
    angle = 2 * np.pi * frequency * t
    design = np.column_stack([np.sin(angle), np.cos(angle), np.ones(len(t))])
    if len(t) < 4 or np.linalg.matrix_rank(design) < 3:
        raise ValueError('Insufficient independent samples for sine fitting')
    fits = []
    for values in (signal, response):
        values = np.asarray(values, dtype=float)
        if not np.isfinite(values).all():
            raise ValueError('Nonfinite sine-fit input')
        coeff, *_ = np.linalg.lstsq(design, values, rcond=None)
        residual = values - design @ coeff
        fits.append((float(np.hypot(*coeff[:2])), float(np.arctan2(coeff[1], coeff[0])),
                     float(np.sqrt(np.mean(residual ** 2)))))
    amplitude_in, phase_in, residual_in = fits[0]
    amplitude_out, phase_out, residual_out = fits[1]
    if amplitude_in < 1e-10:
        raise ValueError('Input sine amplitude is too small')
    gain = amplitude_out / amplitude_in
    phase = float((np.degrees(phase_out - phase_in) + 180) % 360 - 180)
    return dict(input_amplitude=amplitude_in, output_amplitude=amplitude_out,
                amplitude_ratio=gain, magnitude_db=float(20 * np.log10(gain)) if gain > 1e-12 else None,
                phase_degrees=phase if gain > 1e-12 else None,
                input_fit_rmse=residual_in, response_fit_rmse=residual_out,
                tracking_rmse=float(np.sqrt(np.mean((np.asarray(response) - signal) ** 2))))


def select_fixed_hour(tracking):
    """First complete 17:00-18:00 simulation-time window with its full lead-in."""
    times = pd.DatetimeIndex(tracking['Time']).sort_values()
    if len(times) < 2 or not times.is_unique:
        raise ValueError('Tracking must have unique timestamps and at least two samples')
    step = pd.Series(times).diff().dropna().median()
    if step <= pd.Timedelta(0) or pd.Timedelta(hours=1) % step != pd.Timedelta(0):
        raise ValueError('Timestep must be positive and divide one hour')
    for day in times.normalize().unique():
        start = day + pd.Timedelta(hours=17)
        lead = start - pd.Timedelta(minutes=LEAD_IN_MINUTES)
        end = start + pd.Timedelta(hours=1)
        expected = pd.date_range(lead, end, freq=step, inclusive='left')
        actual = times[(times >= lead) & (times < end)]
        if actual.equals(expected):
            return start
    raise ValueError('No complete 17:00-18:00 simulation-time window with a '
                     'complete 16:30-17:00 lead-in was found')


def run_hour(b2, baseline_dir, screen_signal, start, frequency, run_dir):
    """Use B2 dispatch/stepping directly; replay states rather than start cold."""
    baseline, _, manifest, homes = b2.load_baseline_run(str(baseline_dir))
    settings = b2.CONFIG
    # The screening B2 run validated these settings and input hashes against B1.
    # Validate again for each trial, rather than silently accept changed inputs.
    ignored = {'REG_TYPE', 'REG_SIGNAL', 'REG_ADDRESS', 'REG_DIR', 'RESULTS_DIR',
               'FEEDBACK_GAIN', 'TRACKING_DEADBAND_KW', 'MAX_RESPONSE_CHANGE_KW_PER_INTERVAL',
               'FLEET_WORKERS', 'NUMERICAL_THREADS', 'MIN_HOLD_MINUTES', 'MIN_HOLD_STEPS',
               'REGULATION_CAPACITY_FRACTION', 'CONTINUOUS_POWER_CONTROL', 'CAUSAL_LOOKAHEAD',
               'ENERGY_AWARE_DISPATCH', 'ENERGY_RECOVERY_HOURS', 'REGULATION_CAPACITY_MODE'}
    current = json.loads(json.dumps(settings, default=str))
    for key, value in manifest['configuration'].items():
        if key not in ignored and key in current and current[key] != value:
            raise ValueError(f'Configuration differs from baseline: {key}')
    if b2._file_hash(settings['WEATHER_FILE']) != manifest['weather_sha256']:
        raise ValueError('Weather changed since baseline')
    for home in manifest['homes']:
        for filename, key in ((settings['XML_ADDRESS'], 'xml_sha256'), (settings['CSV_ADDRESS'], 'schedule_sha256')):
            if b2._file_hash(Path(home['path']) / filename) != home[key]:
                raise ValueError(f"Baseline input changed: {home['name']} / {filename}")
    run_dir.mkdir()
    metadata = dict(status='running', baseline_dir=str(baseline_dir), selected_hour=start,
                    frequency_cycles_per_minute=frequency, prehistory='screening signal replay',
                    lead_in_minutes=LEAD_IN_MINUTES)
    write_json(run_dir / 'sweep_trial.json', metadata)
    try:
        fleet = []
        for i, home in enumerate(homes, 1):
            result = b2.init_fleet_worker(home)
            if not result['success']:
                raise RuntimeError(f"Initialization failed: {home}: {result['error']}")
            fleet.append(result)
            if i == 1 or i % 20 == 0 or i == len(homes):
                print(f'Initialized {i}/{len(homes)} homes', flush=True)
        times = pd.DatetimeIndex(fleet[0]['controlled'].sim_times)
        if any(not times.equals(pd.DatetimeIndex(h['controlled'].sim_times)) for h in fleet):
            raise ValueError('Fleet time grids differ')
        if any(type(eq).__module__.endswith('WetAppliance') for h in fleet for eq in h['controlled'].equipment.values()):
            raise ValueError('WetAppliance requires isolated random generators')
        end = start + pd.Timedelta(hours=1)
        lead = start - pd.Timedelta(minutes=LEAD_IN_MINUTES)
        times = times[times < end]
        signal = screen_signal.copy()
        trial_times = signal.index[(signal.index >= lead) & (signal.index < end)]
        elapsed = (trial_times - lead).total_seconds() / 60
        signal.loc[trial_times] = np.sin(2 * np.pi * frequency * elapsed)
        base_power = baseline.groupby('Time')['Total Electric Power (kW)'].sum()
        up = float(manifest['summary']['up_regulation_capacity_kw'])
        down = float(manifest['summary']['down_regulation_capacity_kw'])
        if settings.get('REGULATION_CAPACITY_MODE', 'asymmetric') == 'symmetric':
            up = down = min(up, down)
        fraction = float(settings.get('REGULATION_CAPACITY_FRACTION', 1))
        up, down = up * fraction, down * fraction
        previous_actual, previous_signal = 0., None
        rows = []
        with b2.common.numerical_threads(settings), b2.common.fleet_executor(settings) as executor:
            for index, timestamp in enumerate(times):
                reporting = timestamp >= signal.index[0]
                if reporting:
                    value = float(signal.loc[timestamp])
                    slope = 0. if previous_signal is None else value - previous_signal
                    for home in fleet:
                        home['regulation_signal_slope'] = slope if settings.get('CAUSAL_LOOKAHEAD', True) else 0.
                    previous_signal = value
                    dispatch = b2.dispatch_regulation_signal(fleet, value, previous_actual, up, down, settings, timestamp)
                results = b2.common.step_fleet(executor, b2.update_home_worker, fleet, timestamp)
                for home, result in zip(fleet, results):
                    if not result['success']:
                        raise RuntimeError(f"Update failed at {timestamp}: {result['error']}")
                    home['last_controlled_kw'] = result['controlled_kw']
                    home['devices'] = result['devices']
                    # No per-home exports are needed; retain only aggregate lead-in/hour.
                    home['controlled'].results.clear()
                if reporting:
                    controlled = sum(r['controlled_kw'] for r in results)
                    base = float(base_power.loc[timestamp])
                    previous_actual = controlled - base
                    if timestamp >= lead:
                        row = {'Time': timestamp, 'Up Capacity (kW)': up, 'Down Capacity (kW)': down,
                               'Baseline Power (kW)': base, 'Controlled Power (kW)': controlled,
                               'Actual Delta (kW)': previous_actual}
                        row.update({k: v for k, v in dispatch.items() if k != 'actions'})
                        rows.append(row)
                if index % max(1, round(60 / settings['t_res'])) == 0:
                    print(f'Replayed/simulated through {timestamp}', flush=True)
        data = pd.DataFrame(rows)
        expected = pd.date_range(lead, end, freq=pd.Timedelta(minutes=settings['t_res']), inclusive='left')
        if not pd.DatetimeIndex(data.Time).equals(expected):
            raise ValueError('Incomplete trial lead-in/hour')
        data.to_csv(run_dir / 'regulation_tracking.csv', index=False)
        metadata['status'] = 'complete'
        return run_dir
    except BaseException as exc:
        metadata.update(status='failed', error=repr(exc))
        raise
    finally:
        write_json(run_dir / 'sweep_trial.json', metadata)


def score_hour(c3, c4, run_dir, start):
    """C4 scores with lead-in history; select only the fixed test hour afterward."""
    # C4's normal resolver requires full per-home B2 exports. This aggregate-only
    # trial uses the identical C4 main/scoring code with a local path resolver.
    # A private globals dictionary leaves the imported module unchanged.
    scoring_globals = dict(c4.main.__globals__)
    scoring_globals['resolve_run'] = lambda run_dir=None, run_id=None: Path(run_dir)
    score_main = types.FunctionType(c4.main.__code__, scoring_globals,
                                   c4.main.__name__, c4.main.__defaults__)
    score_main(run_dir=run_dir)
    hourly = pd.read_csv(run_dir / 'Ready_data' / 'C4_hourly_scores.csv', parse_dates=['Time'])
    selected = hourly.loc[hourly.Time == start]
    if len(selected) != 1:
        raise ValueError('C4 did not score the selected hour')
    response = c3.load_normalized_response(run_dir / 'regulation_tracking.csv')
    response = response.loc[(response.Time >= start) & (response.Time < start + pd.Timedelta(hours=1))]
    response.to_csv(run_dir / 'selected_hour_response.csv', index=False)
    return selected.iloc[0], response


def plot_results(output, rows):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    frame = pd.DataFrame(rows)
    for column, label, filename, ideal in (
            ('magnitude_db', 'Magnitude (dB)', 'bode_magnitude.pdf', 0),
            ('phase_degrees', 'Response phase relative to signal (degrees)', 'bode_phase.pdf', 0)):
        fig, ax = plt.subplots(figsize=(7, 4.5))
        if not frame.empty:
            ax.semilogx(frame.frequency_cycles_per_minute, pd.to_numeric(frame[column]), 'o-', color='black')
            failed = frame.loc[~frame.passed]
            if not failed.empty:
                ax.scatter(failed.frequency_cycles_per_minute, pd.to_numeric(failed[column]), marker='x',
                           s=90, color='black', label='C4 score below threshold', zorder=3)
                ax.legend()
        ax.axhline(ideal, linestyle='--', color='gray', linewidth=1)
        ax.set(xlabel='Frequency (cycles/minute)', ylabel=label,
               title='Selected-hour regulation frequency response')
        ax.grid(True, which='both', alpha=.25)
        fig.tight_layout()
        fig.savefig(output / filename)
        plt.close(fig)


def run_sweep(threshold=THRESHOLD, start_frequency=START_FREQUENCY,
              frequency_step=FREQUENCY_STEP, max_iterations=MAX_ITERATIONS, output_dir=None):
    if not np.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError('Threshold must be between zero and one')
    if any(not np.isfinite(x) or x <= 0 for x in (start_frequency, frequency_step)):
        raise ValueError('Frequencies must be finite and positive')
    if max_iterations < 1:
        raise ValueError('max_iterations must be positive')
    b2, c3, c4, latest = modules()
    timestep = float(b2.CONFIG['t_res'])
    if not np.isfinite(timestep) or not 0 < timestep <= c4.MAX_TIMESTEP_MINUTES:
        raise ValueError('Timestep is incompatible with C4')
    if start_frequency >= .5 / timestep:
        raise ValueError('Starting frequency must be below Nyquist')
    baseline_dir = latest(b2.CONFIG.get(
        'RESULTS_DIR', Path(__file__).resolve().parent / 'Results'))
    sweep_id = dt.datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8]
    output = Path(output_dir) if output_dir else baseline_dir / 'BodeSweeps_17to18'
    output = output.resolve() / sweep_id
    output.mkdir(parents=True)
    summary = dict(status='screening', baseline_dir=str(baseline_dir), threshold=threshold,
                   start_frequency=start_frequency, frequency_step=frequency_step,
                   max_iterations=max_iterations, lead_in_minutes=LEAD_IN_MINUTES,
                   phase_convention='output minus input, wrapped to [-180,180); negative means lag',
                   magnitude_convention='20 log10(output fundamental amplitude / input amplitude)',
                   hour_selection='First complete 17:00-18:00 window in simulation time; no performance ranking')
    rows = []
    try:
        write_json(output / 'summary.json', summary)
        print(f'Baseline: {baseline_dir}\nSweep output: {output}', flush=True)
        screen = b2.main(str(baseline_dir), sine_freq=start_frequency)
        screen_dir = Path(screen['manifest_path']).parent
        summary['screening_run_dir'] = str(screen_dir)
        tracking = c3.load_tracking(screen_dir / 'regulation_tracking.csv')
        start = select_fixed_hour(tracking)
        summary.update(status='sweeping', selected_hour_start=start, selected_hour_end=start + pd.Timedelta(hours=1))
        screen_signal = tracking.set_index('Time')['Regulation Signal']
        print(f'Fixed test hour: {start} to {start + pd.Timedelta(hours=1)} (simulation time)', flush=True)
        for iteration in range(max_iterations):
            frequency = start_frequency + iteration * frequency_step
            if frequency >= .5 / timestep:
                summary['status'] = 'nyquist_limit_reached'
                break
            print(f'Trial {iteration + 1}: {frequency:g} cycles/min', flush=True)
            run_dir = output / f'trial_{iteration + 1:03d}'
            run_hour(b2, baseline_dir, screen_signal, start, frequency, run_dir)
            score, response = score_hour(c3, c4, run_dir, start)
            elapsed = (response.Time - start).dt.total_seconds().to_numpy() / 60
            measurements = fit_response(elapsed, response['Regulation Signal'].to_numpy(),
                                        response.normalized_actual_response.to_numpy(), frequency)
            performance = float(score.Performance)
            if not np.isfinite(performance):
                raise ValueError('C4 score is nonfinite')
            passed = performance >= threshold
            row = dict(iteration=iteration + 1, frequency_cycles_per_minute=frequency,
                       frequency_hz=frequency / 60, period_minutes=1 / frequency,
                       cycles_in_hour=frequency * 60, samples_per_cycle=1 / (frequency * timestep),
                       few_cycles=frequency * 60 < 3, score=performance, correlation=float(score.Correlation),
                       delay=float(score.Delay), precision=float(score.Precision), passed=passed,
                       run_dir=str(run_dir), **measurements)
            rows.append(row)
            results = pd.DataFrame(rows)
            results.to_csv(output / 'frequency_results.csv', index=False)
            # RMSE compares the normalized actual response directly to the signal
            # (no lag adjustment). Delay is C4's dimensionless score, not minutes.
            results[[
                'frequency_cycles_per_minute', 'frequency_hz', 'tracking_rmse',
                'precision', 'correlation', 'delay', 'score',
            ]].rename(columns={
                'tracking_rmse': 'normalized_tracking_rmse',
                'precision': 'precision_score',
                'correlation': 'correlation_score',
                'delay': 'delay_score',
                'score': 'performance_score',
            }).to_csv(output / 'frequency_scores.csv', index=False)
            plot_results(output, rows)
            summary['completed_trials'] = len(rows)
            if passed:
                summary['last_passing_frequency'] = frequency
            else:
                summary.update(status='threshold_failed', failed_frequency=frequency, failed_score=performance)
            write_json(output / 'summary.json', summary)
            print(f'C4 selected-hour score: {performance:.6f}; {"PASS" if passed else "FAIL"}', flush=True)
            if not passed:
                break
        else:
            summary['status'] = 'max_iterations_reached'
    except BaseException as exc:
        summary.update(status='interrupted' if isinstance(exc, KeyboardInterrupt) else 'error', error=repr(exc))
        raise
    finally:
        write_json(output / 'summary.json', summary)
    print(f'Finished: {summary["status"]}. Results: {output}', flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--threshold', type=float, default=THRESHOLD)
    parser.add_argument('--start-frequency', type=float, default=START_FREQUENCY)
    parser.add_argument('--frequency-step', type=float, default=FREQUENCY_STEP)
    parser.add_argument('--max-iterations', type=int, default=MAX_ITERATIONS)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    run_sweep(**vars(args))


if __name__ == '__main__':
    main()
