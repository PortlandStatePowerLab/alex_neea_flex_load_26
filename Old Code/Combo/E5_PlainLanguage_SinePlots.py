"""Plot saved sine-sweep results with plain-language labels (no simulations).

Run: python E5_PlainLanguage_SinePlots.py
Optional: --run-dir PATH --output-dir PATH
Creates PDF and PNG versions of two figures in the sweep's PlainLanguagePlots folder.
"""
import argparse
from pathlib import Path
import textwrap

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parent


def select_run(run_dir=None):
    if run_dir:
        run = Path(run_dir).expanduser().resolve()
        if not (run / 'frequency_results.csv').is_file():
            raise FileNotFoundError(f'No frequency_results.csv in {run}')
        return run
    candidates = [p for p in (ROOT / 'Results').rglob('frequency_results.csv')
                  if p.parent.parent.name in ('BodeSweeps', 'BodeSweeps_17to18')]
    if not candidates:
        raise FileNotFoundError('No saved sine sweeps found. Specify --run-dir.')
    return max(candidates, key=lambda p: (p.parent.name, p.stat().st_mtime_ns)).parent


def caption(fig, text):
    fig.text(.08, .025, textwrap.fill(text, 125), ha='left', va='bottom', fontsize=10)


def save(fig, output, name):
    for extension in ('pdf', 'png'):
        fig.savefig(output / f'{name}.{extension}', dpi=200)
    plt.close(fig)


def load_response(run, row):
    # Prefer local trial data: saved absolute paths may refer to an older location.
    trial = run / f'trial_{int(row.iteration):03d}'
    path = trial / 'selected_hour_response.csv'
    if not path.is_file() and 'run_dir' in row.index:
        path = Path(str(row.run_dir)) / 'selected_hour_response.csv'
    if not path.is_file():
        raise FileNotFoundError(f'Missing saved response: {path}')
    data = pd.read_csv(path, usecols=['Time', 'Regulation Signal', 'normalized_actual_response'])
    data['Time'] = pd.to_datetime(data['Time'], errors='raise')
    data = data.sort_values('Time')
    if data.empty or data.Time.duplicated().any():
        raise ValueError(f'Empty response or duplicate timestamps: {path}')
    values = data[['Regulation Signal', 'normalized_actual_response']].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError(f'Nonfinite response values: {path}')
    return data


def plot(run_dir=None, output_dir=None):
    run = select_run(run_dir)
    frame = pd.read_csv(run / 'frequency_results.csv')
    required = {'iteration', 'frequency_cycles_per_minute', 'score'}
    if frame.empty or not required.issubset(frame.columns):
        raise ValueError(f'Expected nonempty results with columns {sorted(required)}')
    for key in required:
        frame[key] = pd.to_numeric(frame[key], errors='raise')
    if (not np.isfinite(frame[list(required)].to_numpy()).all()
            or (frame.frequency_cycles_per_minute <= 0).any()
            or not frame.score.between(0, 1).all()):
        raise ValueError('Frequencies must be positive and scores must be finite values from 0 to 1.')
    frame['period_minutes'] = 1 / frame.frequency_cycles_per_minute
    frame = frame.sort_values('period_minutes').reset_index(drop=True)
    best, worst = frame.loc[frame.score.idxmax()], frame.loc[frame.score.idxmin()]
    # Load both before writing figures so missing trial files produce a clear error.
    examples = [(label, row, load_response(run, row))
                for label, row in [('Highest score', best), ('Lowest score', worst)]]
    output = Path(output_dir).expanduser().resolve() if output_dir else run / 'PlainLanguagePlots'
    output.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({'font.size': 12, 'axes.titlesize': 15, 'axes.labelsize': 12})

    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.semilogx(frame.period_minutes, 100 * frame.score, 'o-', color='#315b8a', lw=2)
    for label, row, color, offset in [('Highest score', best, '#19754b', (-75, -60)),
                                       ('Lowest score', worst, '#ad442c', (12, -40))]:
        ax.scatter(row.period_minutes, 100 * row.score, s=90, color=color, zorder=4)
        ax.annotate(f'{label}: {100 * row.score:.1f}%\n{row.period_minutes:.3g} min per cycle',
                    (row.period_minutes, 100 * row.score), xytext=offset,
                    textcoords='offset points', fontsize=10)
    ticks = np.array([1, 2, 3, 5, 10, 20, 30, 50, 100, 200, 500, 1000], dtype=float)
    ticks = ticks[(ticks >= frame.period_minutes.min()) & (ticks <= frame.period_minutes.max())]
    if len(ticks) < 2:
        ticks = np.geomspace(frame.period_minutes.min(), frame.period_minutes.max(), 4)
    ax.set_xticks(np.unique(np.round(ticks, 2)))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f'{x:g}'))
    ax.set(title='How well do flexible loads follow changes at different speeds?',
           xlabel='Time for one full signal cycle (minutes; longer cycles to the right)',
           ylabel='Performance score (%)\n100% is ideal', ylim=(0, 105))
    ax.grid(True, which='major', alpha=.25)
    caption(fig, 'Each dot is one tested sinusoidal signal. Higher scores indicate better overall regulation performance. '
            'Cycle lengths use a logarithmic scale. Lines connect tested points; intermediate cycle lengths were not tested.')
    fig.subplots_adjust(left=.12, right=.83, top=.88, bottom=.28)
    save(fig, output, 'performance_vs_signal_period')

    fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharey=True)
    max_response = max(float(np.abs(d[['Regulation Signal', 'normalized_actual_response']]).max().max())
                       for _, _, d in examples)
    for ax, (label, row, data) in zip(axes, examples):
        minutes = (data.Time - data.Time.iloc[0]).dt.total_seconds() / 60
        ax.plot(minutes, 100 * data['Regulation Signal'], '--', color='black', lw=1.8,
                label='Requested change (signal)')
        ax.plot(minutes, 100 * data.normalized_actual_response, color='#315b8a', lw=2,
                label='Actual change (flexible loads)')
        ax.axhline(0, color='gray', lw=.7)
        ax.set(title=f'{label}: {100 * row.score:.1f}% | One cycle takes {row.period_minutes:.3g} minutes',
               xlabel=f'Minutes after {data.Time.iloc[0]:%H:%M} (simulation time)',
               ylabel='Change in electricity use\n(% of regulation capacity)',
               ylim=(-110 * max(1, max_response), 110 * max(1, max_response)))
        ax.grid(alpha=.25)
    axes[0].legend(loc='upper left', fontsize=10)
    fig.suptitle('Best and worst response among the tested signals', fontsize=17, y=.98)
    caption(fig, 'Closer overlap means better tracking. Positive values mean increased electricity use; negative values mean '
            'reduced use, relative to baseline. Values use the applicable direction-specific regulation capacity. '
            'Examples are ranked by saved performance score; each shows the saved test hour, which may contain less than a full cycle.')
    fig.subplots_adjust(left=.13, right=.97, top=.89, bottom=.19, hspace=.55)
    save(fig, output, 'best_and_worst_signal_responses')
    print(f'Sweep: {run}\nFigures: {output}')
    for label, row, _ in examples:
        print(f'{label}: trial {int(row.iteration)}, {row.period_minutes:.3g} min/cycle, score {100 * row.score:.2f}%')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path)
    parser.add_argument('--output-dir', type=Path)
    plot(**vars(parser.parse_args()))

