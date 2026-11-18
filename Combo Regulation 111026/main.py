import xlwings as xw
import argparse
from pathlib import Path
import subprocess
import sys

def read_Excel(workbook_path):
    wb = xw.Book(workbook_path)
    py_vals = wb.sheets("PythonVals")

    A1 = py_vals.range("A1").value

    py_vals.range("A2").value = workbook_path


def main():
    parser = argparse.ArgumentParser(description="Path to Excel Workbook")
    parser.add_argument("--workbook", default=".", help="Path to the Excel Workbook")
    args = parser.parse_args()


    read_Excel(args.workbook)

    test_script = Path(__file__).resolve().parent / "Setup" / "testing.py"

    subprocess.run(
        [sys.executable, "-u", str(test_script)],
        check=True,
    )

if __name__ == "__main__":
    main()