"""Replot saved E3 Bode results at 10 x 5 inches, without simulations.

Run: python Combo/E3_Replot.py
Or:  python Combo/E3_Replot.py --run-dir path/to/BodeSweeps/sweep_id
The default selects the newest saved E3 CSV in a BodeSweeps folder anywhere
under Combo/Results.
PDFs are saved in the sweep's Replot_10x5 folder unless --output-dir is given.
Only pandas and matplotlib are required; no simulation modules are imported.
"""

import argparse
from pathlib import Path

import pandas as pd


RESULTS_DIR = Path(__file__).resolve().parent / 'Results'


def select_run(run_dir=None):
    if run_dir is not None:
        path = Path(run_dir).expanduser().resolve()
        if not (path / 'frequency_results.csv').is_file():
            raise FileNotFoundError(f'No frequency_results.csv in {path}')
        return path
    candidates = list(RESULTS_DIR.glob('**/BodeSweeps/*/frequency_results.csv'))
    if not candidates:
        raise FileNotFoundError(
            f'No saved E3 results found under {RESULTS_DIR}. '
            'Use --run-dir to select an existing E3 sweep folder.'
        )
    return max(candidates, key=lambda p: (p.stat().st_mtime_ns, str(p))).parent


def replot(run_dir=None, output_dir=None):
    run = select_run(run_dir)
    frame = pd.read_csv(run / 'frequency_results.csv')
    required = {'frequency_cycles_per_minute', 'magnitude_db', 'phase_degrees', 'passed'}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f'frequency_results.csv is missing columns: {sorted(missing)}')
    if frame.empty:
        raise ValueError('frequency_results.csv contains no saved trials')
    # Parse explicitly so CSV strings such as "False" retain the failure marker.
    passed = frame['passed'].astype(str).str.strip().str.lower().map(
        {'true': True, 'false': False})
    if passed.isna().any():
        raise ValueError('The passed column must contain True or False')
    frame['passed'] = passed.astype(bool)
    for column in ('frequency_cycles_per_minute', 'magnitude_db', 'phase_degrees'):
        frame[column] = pd.to_numeric(frame[column], errors='raise')
    output = Path(output_dir).expanduser().resolve() if output_dir else run / 'Replot_10x5'
    output.mkdir(parents=True, exist_ok=True)

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    # Retain the E3 data and styling with larger text for readability.
    for column, label, filename, ideal in (
            ('magnitude_db', 'Magnitude (dB)', 'bode_magnitude.pdf', 0),
            ('phase_degrees', 'Response phase relative\nto signal (degrees)', 'bode_phase.pdf', 0)):
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.semilogx(frame.frequency_cycles_per_minute, frame[column], 'o-', color='black')
        failed = frame.loc[~frame.passed]
        if not failed.empty:
            ax.scatter(failed.frequency_cycles_per_minute, failed[column], marker='x',
                       s=90, color='black', label='C4 score below threshold', zorder=3)
            ax.legend(fontsize=14)
        ax.axhline(ideal, linestyle='--', color='gray', linewidth=1)
        ax.set(xlabel='Frequency (cycles/minute)', ylabel=label)
        ax.xaxis.label.set_size(16)
        ax.yaxis.label.set_size(16)
        ax.tick_params(axis='both', which='both', labelsize=14)
        ax.grid(True, which='both', alpha=.25)
        fig.tight_layout()
        fig.savefig(output / filename)
        plt.close(fig)
    print(f'Loaded: {run / "frequency_results.csv"}')
    print(f'Saved 10 x 5 inch Bode PDFs: {output}')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, help='Existing E3 sweep folder')
    parser.add_argument('--output-dir', type=Path, help='Destination for the two PDFs')
    args = parser.parse_args()
    replot(**vars(args))


if __name__ == '__main__':
    main()
