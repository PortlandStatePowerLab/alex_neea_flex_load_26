"""Plot baseline versus regulation results from separated B1 and B2 runs.

Run directly for the latest completed pair, or use --run-dir <result folder>.
C1 tables are regenerated automatically. Use --no-show to save plots only.
"""

import argparse
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

try:
    from .C1_parse_OCHRE_data_final import METRICS, parse_run, select_run
except ImportError:
    from C1_parse_OCHRE_data_final import METRICS, parse_run, select_run

RUN_DIR = None  # Set a specific result folder here, or use --run-dir.


def plot_run(run_dir, show=True):
    if not show:
        plt.switch_backend("Agg")
    tables = parse_run(run_dir)
    output_dir = Path(run_dir) / "Ready_data"
    averages = {}
    for column, pair in tables.items():
        suffix, title = METRICS[column]
        # Compute from homes each time; never append averages to C1's tables.
        average = pd.DataFrame({kind: table.mean(axis=0)
                                for kind, table in pair.items()})
        average.index.name = "Time"
        average.to_csv(output_dir / f"{Path(run_dir).name}_{suffix}_averages.csv")
        averages[column] = average
        is_soc = "SOC" in column
        fig, ax = plt.subplots(figsize=(10, 5))
        for kind, color in (("baseline", "#004C6D"), ("controlled", "#E26D28")):
            ax.plot(average.index, average[kind] * (100 if is_soc else 1),
                    label=kind.title(), color=color, linewidth=1.5)
        ax.set_title(f"Average {title.lower()} per reporting home")
        ax.set_ylabel("State of charge (%)" if is_soc else "Power (kW/home)")
        locator = mdates.AutoDateLocator(minticks=3, maxticks=8)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        ax.grid(True, alpha=0.3)
        ax.legend()
        fig.tight_layout()
        fig.savefig(output_dir / f"{Path(run_dir).name}_{suffix}_plot.png", dpi=180)
        if not show:
            plt.close(fig)
    print(f"Comparison plots and averages saved to: {output_dir}")
    if show:
        plt.show()
    return averages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=RUN_DIR)
    parser.add_argument("--no-show", action="store_true")
    args = parser.parse_args()
    plot_run(select_run(args.run_dir), show=not args.no_show)


if __name__ == "__main__":
    main()
