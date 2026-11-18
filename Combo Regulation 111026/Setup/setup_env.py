import sys
import pathlib
from tkinter.filedialog import askdirectory
import venv
import subprocess
import argparse
import tkinter

PROJECT_FOLDER = pathlib.Path(__file__).resolve().parent.parent
VENV_FOLDER = PROJECT_FOLDER / ".venv"
REQS_FILE = PROJECT_FOLDER / "requirements.txt"
MAIN_SCRIPT = PROJECT_FOLDER / "F1_Main.py"


REQUIRED_PYTHON = (3, 12, 10)


def check_python_version():
    current_version = sys.version_info[:3]

    required_text = ".".join(map(str, REQUIRED_PYTHON))
    current_text = ".".join(map(str, current_version))

    # print(f"Python executable: {sys.executable}")
    # print(f"Required version: {required_text}")
    # print(f"Current version:  {current_text}")

    if current_version != REQUIRED_PYTHON:
        raise RuntimeError(
            f"This project requires Python {required_text}, "
            f"but this script is running with Python {current_text}. "
            "Install the required version separately, then run "
            "this setup script using that installation."
        )

    # print(f"Project folder: {PROJECT_FOLDER}")
    # print(f"Virtual environment folder: {VENV_FOLDER}")
    # print(f"Requirements file: {REQS_FILE}")
    # print(f"Main script: {MAIN_SCRIPT}")

    if not REQS_FILE.is_file():
        raise RuntimeError(f"Requirements file not found: {REQS_FILE}")
    if not MAIN_SCRIPT.is_file():
        raise RuntimeError(f"Main script not found: {MAIN_SCRIPT}")
    
    # if VENV_FOLDER.exists():
    #     print("venv exists")

    # print("Python version is correct.")


# def find_python_exe():
#     if sys.platform == "win32":
#         return pathlib.Path(sys.executable).parent / "python.exe"
#     else:
#         return pathlib.Path(sys.executable)


def make_venv():
    if not VENV_FOLDER.exists():
        venv.create(VENV_FOLDER, with_pip=True)
    python_venv = VENV_FOLDER / "Scripts" / "python.exe" if sys.platform == "win32" else VENV_FOLDER / "bin" / "python"
    if not python_venv.exists():
        raise RuntimeError("Failed to create virtual environment.")

    py_ver = subprocess.run([str(python_venv), "--version"], capture_output=True, text=True, check=True, timeout=10)
    py_ver = tuple(map(int, py_ver.stdout.strip().split(" ")[1].split(".")))

    if not py_ver == REQUIRED_PYTHON:
        raise RuntimeError("Virtual environment has incorrect Python version.")

    return python_venv
        # print("Creating virtual environment...")
        # Add code to create the virtual environment here
    # else:
        # print("Virtual environment already exists.")

def reqs(py_venv_path):
    if not REQS_FILE.is_file():
        raise RuntimeError(f"Requirements file not found: {REQS_FILE}")

    subprocess.run([str(py_venv_path), "-m", "pip", "install", "-r", str(REQS_FILE)], check=True, cwd=PROJECT_FOLDER)
    print("Requirements installed successfully.")

    return py_venv_path


def run_script(py_venv_path, results_folder):
    if not MAIN_SCRIPT.is_file():
        raise RuntimeError(f"Simulation script not found: {MAIN_SCRIPT}")

    subprocess.run(
        [
            str(py_venv_path),
            "-u",
            str(MAIN_SCRIPT),
            "--output-folder",
            str(results_folder),
        ],
        check=True,
        cwd=PROJECT_FOLDER,
    )

    print("Simulation script completed successfully.", flush=True)


def pick_results_folder():
    try:
        root = tkinter.Tk()
        root.withdraw()  # Hide the main window
        folder_path = askdirectory(title="Select Simulation Results Folder", parent=root, mustexist=True)

        if folder_path == "":
            raise RuntimeError("No results folder selected.")
        else:
            folder_path = pathlib.Path(folder_path).resolve()
            if not folder_path.is_dir():
                raise RuntimeError(f"Selected folder is not a directory: {folder_path}")
    finally:
        root.destroy()
    return folder_path

def main():

    # results_folder = pick_results_folder()

    # parser = argparse.ArgumentParser(description="Path to Excel Workbook")
    # parser.add_argument("--workbook", default=".", help="Path to the Excel Workbook")
    # args = parser.parse_args()
    # print(args.workbook)

    # EXCEL_WB = pathlib.Path(args.workbook).resolve()

    # if not EXCEL_WB.is_file() or not (EXCEL_WB.suffix == ".xlsx" or EXCEL_WB.suffix == ".xlsm"):
    #     raise RuntimeError(f"Excel workbook not found or is in an invalid format: {EXCEL_WB}")

    try:
        results_folder = pick_results_folder()
        print("Starting simulation...")
        curr_stage = "Checking Python version..."
        print(f"STAGE|{curr_stage}", flush=True)
        check_python_version()
        curr_stage = "Preparing virtual environment..."
        print(f"STAGE|{curr_stage}", flush=True)
        py_venv_path = make_venv()
        curr_stage = "Installing requirements..."
        print(f"STAGE|{curr_stage}", flush=True)
        reqs(py_venv_path)
        curr_stage = "Running main script..."
        print(f"STAGE|{curr_stage}", flush=True)
        run_script(py_venv_path, results_folder)
        print("Simulation completed successfully.")
    except RuntimeError as e:
        print(f"Runtime error occurred: {e}")
        print(f"Stage reached: {curr_stage}")
        sys.exit(1)
    except subprocess.CalledProcessError as f:
        print(f"Subprocess error occurred: {f}")
        print(f"Stage reached: {curr_stage}")
        sys.exit(1)
    except subprocess.TimeoutExpired as g:
        print(f"Subprocess timeout occurred: {g}")
        print(f"Stage reached: {curr_stage}")
        sys.exit(1)
    except OSError as h:
        print(f"OS error occurred: {h}")
        print(f"Stage reached: {curr_stage}")
        sys.exit(1)

if __name__ == "__main__":
    main()