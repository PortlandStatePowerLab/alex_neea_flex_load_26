import subprocess
import tkinter as tk
from tkinter import ttk, messagebox
import time
import argparse
import sys
import threading
import queue
import re
from tkinter.scrolledtext import ScrolledText


def pin_to_top(root, on_top):
    if on_top:
        root.attributes("-topmost", True)
    else:
        root.attributes("-topmost", False)


def close_handler(root, sim_running):
    if sim_running:
        messagebox.showinfo("Simulation Running", "The simulation is still running. Please wait for it to finish before closing the monitor.", parent=root)
        return
    else:
        root.destroy()

def bkd_rdr(process, queueue):
    buffer = bytearray()
    while True:
        curr_mess = process.stdout.read(1)

        if curr_mess == b"":
            if buffer:
                queueue.put(buffer.decode(errors="replace"))
                # curr_mess = buffer.decode(errors="replace")
            break
        elif curr_mess == b"\n" or curr_mess == b"\r":
            if buffer:
                # curr_mess = buffer.decode(errors="replace")
                queueue.put(buffer.decode(errors="replace"))
                buffer.clear()
        else:
            buffer.extend(curr_mess)

def make_monitor(cmd_list):
    cmd_list = [cmd_list[0], "-u", *cmd_list[1:]]

    root = tk.Tk()
    root.title("Monitor")
    root.geometry("350x250")

    status = tk.StringVar(root)
    time_remaining = tk.StringVar(root)
    progress = tk.DoubleVar(root)
    on_top = tk.BooleanVar(root)
    show_output = tk.BooleanVar(root, value=False)

    # test_steps = 100
    # comp_steps = 0
    # start_time = time.perf_counter()

    sim_running = True

    stop_requested = False
    stop_process = None

    progress_pattern = re.compile(
        r"^(?P<description>.+):\s*\d+(?:\.\d+)?%\|[^|]*\|\s*"
        r"(?P<completed>\d+)/(?P<total>\d+)\s*"
        r"\[Elapsed:\s*[^|]+\|\s*ETR:\s*(?P<remaining>[^\]]+)\]"
    )

    def stop_simulation():
        nonlocal stop_requested, stop_process

        if not sim_running or sim.poll() is not None or stop_requested:
            return

        try:
            stop_process = subprocess.Popen(
                [
                    "taskkill",
                    "/PID", str(sim.pid),
                    "/T",
                    "/F",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except OSError as error:
            messagebox.showerror(
                "Unable to stop",
                str(error),
                parent=root,
            )
            return

        stop_requested = True
        stop_button.configure(state="disabled")
        status.set("Stopping simulation...")

    def check_sim():
        nonlocal sim_running
        nonlocal stop_requested, stop_process

        if stop_process is not None:
            stop_code = stop_process.poll()

            if stop_code is None:
                root.after(100, check_sim)
                return

            if stop_code != 0 and sim.poll() is None:
                stop_requested = False
                stop_button.configure(state="normal")
                status.set("Unable to stop - simulation still running")
                messagebox.showerror(
                    "Unable to stop",
                    "Windows could not stop the process tree. "
                    "The simulation is still running.",
                    parent=root,
                )
                stop_process = None
                root.after(100, check_sim)
                return
    
        return_code = sim.poll()

        if return_code is None:
            root.after(100, check_sim)
            return

        sim_running = False

        stop_button.configure(state="disabled")

        if stop_requested:
            status.set("Stopped - you can close this window")
            time_remaining.set("Time remaining: stopped")
            return

        if return_code == 0:
            status.set("Finished - you can close this window")
            messagebox.showinfo(
                "Simulation complete",
                "The simulation completed successfully.",
                parent=root,
            )
            root.destroy()
        else:
            status.set("Failed - you can close this window")
            show_output.set(True)
            toggle_output()
            messagebox.showerror(
                "Simulation failed",
                f"The process exited with code {return_code}.\n\n"
                "Scroll through the output for the error details.",
                parent=root,
            )

    def update_output():
        for _ in range(100):
            try:
                message = queueue.get_nowait()
            except queue.Empty:
                break

            output_text.configure(state="normal")
            output_text.insert("end", message + "\n")
            output_text.see("end")
            output_text.configure(state="disabled")

            if message.startswith("STAGE|"):
                if sim_running:
                    status.set(message.split("|", 1)[1])
                    progress.set(0)
                    time_remaining.set("Time remaining: estimating...")
                continue

            match = progress_pattern.search(message.strip())

            if match:
                completed = int(match.group("completed"))
                total = int(match.group("total"))
                remaining = match.group("remaining").strip()

                if total > 0:
                    progress.set(completed / total * 100)

                time_remaining.set(f"Time remaining: {remaining}")

                if sim_running:
                    description = match.group("description").strip()
                    status.set(f"{description}: {completed}/{total}")

        root.after(100, update_output)
    # def update():
    #     nonlocal comp_steps, start_time, sim_running
    #     if comp_steps < test_steps:
    #         comp_steps += 1
    #         progress.set((comp_steps / test_steps) * 100)
    #         elapsed_time = time.perf_counter() - start_time
    #         remaining_time = elapsed_time / comp_steps * (test_steps - comp_steps)
    #         time_remaining.set(f"{int(remaining_time // 60):02d}:{int(remaining_time % 60):02d}")
    #         root.after(100, update)
    #     else:
    #         sim_running = False
    #         status.set("Simulation finished — you can close this window")

    # def finish_test():
    #     nonlocal sim_running
    #     sim_running = False
    #     status.set("Finished — you can close this window")

    status.set("Starting simulation...")
    time_remaining.set("Time remaining: estimating...")
    progress.set(0)

    label_status = ttk.Label(root, text="Status:", textvariable=status)
    label_time = ttk.Label(root, text="Time Remaining:", textvariable=time_remaining)
    checkbutton = ttk.Checkbutton(root, text="Pin to Top?", variable=on_top, command=lambda: pin_to_top(root, on_top.get()))

    progress_frame = ttk.Frame(root)
    progress_frame.pack(fill="x", padx=10, pady=10)

    prog = ttk.Progressbar(
        progress_frame,
        mode="determinate",
        maximum=100,
        variable=progress,
    )
    prog.pack(side="left", fill="x", expand=True)

    percentage_text = tk.StringVar(root, value="0%")

    percentage_label = ttk.Label(
        progress_frame,
        textvariable=percentage_text,
        width=6,
        anchor="e",
    )
    percentage_label.pack(side="right", padx=(5, 0))


    def update_percentage(*_):
        percentage_text.set(f"{progress.get():.0f}%")


    progress.trace_add("write", update_percentage)

    label_status.pack(padx=10, pady=5)
    label_time.pack(padx=10, pady=5)

    stop_button = ttk.Button(
        root,
        text="Stop Simulation",
        command=stop_simulation,
    )
    stop_button.pack(padx=10, pady=5)

    checkbutton.pack(padx=10, pady=10)

    queueue = queue.Queue()
    # captd_output = tk.StringVar(root)
    # captd_output.set("Waiting for output...")

    # label_output = ttk.Label(root, text="Output:", textvariable=captd_output, wraplength=280)
    output_text = ScrolledText(
        root,
        height=12,
        width=70,
        wrap="word",
        state="disabled",
    )
    # label_output.pack(padx=10, pady=5)

    def toggle_output():
        if show_output.get():
            root.geometry("650x450")
            output_text.pack(
                fill="both",
                expand=True,
                padx=10,
                pady=5,
            )
        else:
            output_text.pack_forget()
            root.geometry("350x250")

    style = ttk.Style(root)
    style.configure(
        "Subtle.TCheckbutton",
        font=("Segoe UI", 8),
        foreground="#777777",
    )
    output_checkbox = ttk.Checkbutton(
        root,
        text="Show output",
        variable=show_output,
        command=toggle_output,
        style="Subtle.TCheckbutton",
    )
    output_checkbox.pack(padx=10, pady=5)


    root.protocol("WM_DELETE_WINDOW", lambda: close_handler(root, sim_running))

    # root.after(3000, finish_test)

    try:
        sim = subprocess.Popen(cmd_list, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError as e:
        status.set(f"Error starting simulation: {e}")
        sim_running = False
        stop_button.configure(state="disabled")
    else:
        reader = threading.Thread(
            target=bkd_rdr,
            args=(sim, queueue),
            daemon=True,
        )
        reader.start()
        check_sim()

    update_output()

    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description="Run a script with a monitor")
    parser.add_argument("--py_exe", default=sys.executable)
    parser.add_argument("--script", required=True)
    parser.add_argument("--workbook")
    parser.add_argument("--output-folder")
    parser.add_argument("--show-plots", "--show_plots", action="store_true")
    parser.add_argument("--params")
    parser.add_argument("--results-file")
    parser.add_argument("--script-args", nargs=argparse.REMAINDER, default=[])
    args = parser.parse_args()

    command = [args.py_exe, args.script]

    if args.workbook:
        command.extend(["--workbook", args.workbook])

    if args.output_folder:
        command.extend(["--output-folder", args.output_folder])
    if args.show_plots:
        command.append("--show-plots")
    if args.params is not None:
        command.extend(["--params", args.params])
    if args.results_file:
        command.extend(["--results-file", args.results_file])
    command.extend(args.script_args)
    make_monitor(command)


if __name__ == "__main__":
    main()