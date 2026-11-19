import sys
import pathlib
from tkinter.filedialog import askdirectory
import venv
import subprocess
import argparse
import tkinter

CODE_FOLDER = pathlib.Path(__file__).resolve().parent.parent
PROJECT_FOLDER = CODE_FOLDER.parent
VENV_FOLDER = PROJECT_FOLDER / ".venv"
REQS_FILE = PROJECT_FOLDER / "requirements.txt"
MAIN_SCRIPT = CODE_FOLDER / "F1_Main.py"


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


def prepare_environment():
    """Prepare dependencies before starting the monitored simulation."""
    print("STAGE|Checking Python version...", flush=True)
    check_python_version()
    print("STAGE|Preparing virtual environment...", flush=True)
    python_venv = make_venv()
    print("STAGE|Installing requirements...", flush=True)
    reqs(python_venv)
    print("STAGE|Environment ready; preparing simulation...", flush=True)
    return python_venv


def resolve_results_folder(output_folder=None):
    if output_folder is None:
        return pick_results_folder()
    folder = pathlib.Path(output_folder).expanduser()
    if not folder.is_absolute():
        folder = PROJECT_FOLDER / folder
    folder = folder.resolve()
    if not folder.is_dir():
        raise ValueError(f"Output folder does not exist: {folder}")
    return folder


def run_script(py_venv_path, results_folder, show_plots=False, params=None, results_file=None, monitored=True):
    """Launch the monitor, which owns the F1 subprocess."""
    monitor_script = CODE_FOLDER / "Setup" / "monitor.py"
    for script in (MAIN_SCRIPT, monitor_script):
        if not script.is_file():
            raise RuntimeError(f"Script not found: {script}")
    command = [
        str(py_venv_path), "-u", str(monitor_script),
        "--py_exe", str(py_venv_path), "--script", str(MAIN_SCRIPT),
        "--output-folder", str(results_folder),
    ]
    if not monitored:
        command = [
            str(py_venv_path), "-u", str(MAIN_SCRIPT),
            "--output-folder", str(results_folder),
        ]
    if params is not None:
        command.extend(["--params", params])
    if results_file is not None:
        command.extend(["--results-file", str(results_file)])
    if show_plots:
        command.append("--show-plots")
    print("STAGE|Starting simulation...", flush=True)
    subprocess.run(command, check=True, cwd=PROJECT_FOLDER)


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
    parser = argparse.ArgumentParser(description="Prepare OCHRE and launch the monitored simulation")
    parser.add_argument("--output-folder")
    parser.add_argument("--show-plots", "--show_plots", action="store_true")
    parser.add_argument("--params", required=True, help="JSON simulation parameters")
    args = parser.parse_args()
    results_folder = resolve_results_folder(args.output_folder)
    python_venv = prepare_environment()
    run_script(python_venv, results_folder, show_plots=args.show_plots, params=args.params)


if __name__ == "__main__":
    main()
