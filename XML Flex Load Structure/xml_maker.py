import tkinter as tk
from tkinter import ttk
import xml.etree.ElementTree as ET
import os
from pathlib import Path
import platform
import math
from tkinter import filedialog, messagebox

VERSION = 2.0

script_dir = os.path.dirname(os.path.abspath(__file__))

my_vars = {}
print_vars = {}
fl_type = None

fl_types = ["Type of Flex Load",
            "Heat Pump Water Heater",
            "Electric Resistance Water Heater",
            "HVAC",
            "EV Charger",
            "Dryer",
            "Battery"]

string_vars = ["Model_Number", 
               "Brand",
               "Can_Schedule",
               "App_Exists",
               "Wireless_Connection",
               "Conect_to_ToU_data",
               "Open_Standard",
               "UCM_DCM_Ready",
               "Compliant"]


def read_blank_xml(file_path):
    tree = ET.parse(file_path)

    # Collect unique tags in order of first appearance in the template.
    unique_tags = list(dict.fromkeys(elem.tag for elem in tree.iter()))

    unique_tags.remove(tree.getroot().tag)  # Remove the root tag from the list

    j = 0
    remove_tag = []
    for i in range(len(unique_tags)):
        if unique_tags[i].endswith("Inputs") or unique_tags[i] == "Version":
            remove_tag.append(unique_tags[i])
            j += 1

    for tag in remove_tag:
        unique_tags.remove(tag)

    print_tags = unique_tags.copy()

    question_vars = string_vars[2:]

    print_tags = [tag + "?" if tag in question_vars else tag for tag in print_tags]

    print_tags = [tag.replace("_", " ") for tag in print_tags]

    return unique_tags, print_tags

# make window scrollable
def on_mouse_scroll(event):
    if platform.system() == "Windows":
        my_canv.yview_scroll(int(-1 * (event.delta / 120)), "units")
    elif platform.system() == "Darwin":
        my_canv.yview_scroll(int(-1 * event.delta), "units")
    else: # Linux
        if event.num == 4: my_canv.yview_scroll(-1, "units")
        elif event.num == 5: my_canv.yview_scroll(1, "units")

# show regulation options
def update_reg_options(event=None):
    global my_vars, fl_type, print_vars

    for widget in options_frame.winfo_children():
        widget.destroy()

    selected = cb_fl_type.get()
    my_vars.clear()
    print_vars.clear()
    fl_type = None
    if selected not in fl_types[1:]:
        return

    if cb_fl_type.get() == "Heat Pump Water Heater":
        fl_type = "HPWH"
    elif cb_fl_type.get() == "Electric Resistance Water Heater":
        fl_type = "ERWH"
    elif cb_fl_type.get() == "HVAC":
        fl_type = "HVAC"
    elif cb_fl_type.get() == "EV Charger":
        fl_type = "EV"
    elif cb_fl_type.get() == "Dryer":
        fl_type = "Dryer"
    elif cb_fl_type.get() == "Battery":
        fl_type = "Battery"

    tags, labels = read_blank_xml(os.path.join(script_dir, "Blank XMLs", f"{fl_type}.xml"))
    my_vars.clear()
    print_vars.clear()

    for tag, label in zip(tags, labels):
        if tag in string_vars:
            var = tk.StringVar()
        else:
            var = tk.DoubleVar()
        my_vars[tag] = var
        print_vars[label] = var
   
    show_options(print_vars)
    but_make_xml = tk.Button(options_frame, text="Create XML File", command=make_xml)
    but_make_xml.pack(pady=(10, 20))


# shortcut for entry boxes
def entry_sc(text, var):
    ttk.Label(
        options_frame,
        text=text
    ).pack()
    
    ttk.Entry(
        options_frame,
        textvariable=var
    ).pack(pady=(0, 10))

# shortcut for checkbuttons
def cbut_sc(text, var):
    ttk.Checkbutton(
        options_frame,
        text=text,
        variable=var
    ).pack()

def copy_fill_xml(source_file, destination_file):
    tree = ET.parse(source_file)
    root = tree.getroot()

    for elem in root.iter():
        if elem.tag == "Version":
            elem.text = str(VERSION)
        if elem.tag in my_vars:
            elem.text = str(my_vars[elem.tag].get())

    tree.write(destination_file, encoding="utf-8", xml_declaration=True)


# make the xml file
def make_xml():
    if fl_type is None or cb_fl_type.get() not in fl_types[1:]:
        messagebox.showerror("Select a Load Type", "Please select a flex load type first.")
        return

    model_number = my_vars['Model_Number'].get()
    reserved_names = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    reserved_names.update(prefix + digit for prefix in ("COM", "LPT")
                          for digit in "123456789¹²³")
    if (not model_number.strip()
            or model_number != model_number.strip()
            or model_number.endswith(".")
            or any(char in '<>:"/\\|?*' or ord(char) < 32 for char in model_number)
            or model_number.split(".")[0].rstrip().upper() in reserved_names
            or len(model_number + ".xml") > 255):
        messagebox.showerror(
            "Invalid Model Number",
            "Enter a model number that is a valid Windows filename: no blank names, "
            "reserved names (such as CON), leading/trailing spaces, trailing periods, "
            "or characters < > : \" / \\ | ? *. Maximum length: 251 characters.")
        return

    for tag, var in my_vars.items():
        if tag not in string_vars:
            try:
                valid = math.isfinite(var.get())
            except (tk.TclError, ValueError, OverflowError):
                valid = False
            if not valid:
                messagebox.showerror(
                    "Invalid Numeric Input",
                    f"Please enter a finite number for {tag.replace('_', ' ')}.")
                return

    # output folder will be in specified folder, in new folder labled type of flex load
    # ie user selects hpwh and desktop folder:
    #   created hpwh xml will be in "Heat Pump Water Heater" folder in desktop
    #   xml name will be model number of hpwh
    out_dir = filedialog.askdirectory(
        title="Please Select Output Folder",
        initialdir="/")
    if not out_dir:
        return

    OUT_FOLD = str(cb_fl_type.get())
    OUT_PATH = os.path.join(out_dir, OUT_FOLD)

    output_pathname = os.path.join(OUT_PATH, f"{model_number}.xml")
    if Path(output_pathname).exists() and not messagebox.askyesno(
            "Replace Existing XML?",
            f"{output_pathname} already exists. Replace it?"):
        return

    input_path = os.path.join(script_dir, "Blank XMLs", f"{fl_type}.xml")

    try:
        Path(OUT_PATH).mkdir(parents=True, exist_ok=True)
        copy_fill_xml(input_path, output_pathname)
    except OSError as error:
        messagebox.showerror("XML File Not Created", str(error))
        return

    if Path(output_pathname).is_file():
        top = tk.Toplevel()
        top.title("XML File Created!")
        top.geometry("200x75")
        lbl_ok = tk.Label(top, text="XML File Created!")
        lbl_ok.pack()
        but_ok = tk.Button(top, text="Okay", command=top.destroy)
        but_ok.pack()
    else:
        top = tk.Toplevel()
        top.title("No XML File Created")
        top.geometry("200x75")
        lbl_ok = tk.Label(top, text="XML File Not Created")
        lbl_ok.pack()
        but_ok = tk.Button(top, text="Okay", command=top.destroy)
        but_ok.pack()


def show_options(my_vars):
    vars_keys = list(my_vars.keys())
    for i in range(0, len(vars_keys)):
        entry_sc(vars_keys[i], my_vars[vars_keys[i]])


root = tk.Tk()
root.title("Flex Load XML Creator")
root.geometry("900x600")

main_frame = tk.Frame(root)
main_frame.pack(fill="both", expand=True)
main_frame.columnconfigure(0, weight=1)
main_frame.rowconfigure(0, weight=1)

my_canv = tk.Canvas(main_frame)
my_canv.grid(row=0, column=0, sticky="nsew")

y_scroll = ttk.Scrollbar(main_frame, orient="vertical", command=my_canv.yview)
y_scroll.grid(row=0, column=1, sticky="ns")

my_canv.configure(yscrollcommand=y_scroll.set)

sec_frm = tk.Frame(my_canv)
canvas_window = my_canv.create_window((0, 0), window=sec_frm, anchor="nw")


def resize_scroll_region(event=None):
    my_canv.configure(scrollregion=my_canv.bbox("all"))


def resize_inner_frame(event):
    my_canv.itemconfigure(canvas_window, width=event.width)


sec_frm.bind("<Configure>", resize_scroll_region)
my_canv.bind("<Configure>", resize_inner_frame)
root.bind_all("<MouseWheel>", on_mouse_scroll) # Windows/macOS
root.bind_all("<Button-4>", on_mouse_scroll)   # Linux: scroll up
root.bind_all("<Button-5>", on_mouse_scroll)   # Linux: scroll down

# Widgets are added here
lbl_title = tk.Label(sec_frm, text="Flex Load XML Creator")
lbl_title.pack()

lbl_inst = tk.Label(sec_frm, text=
    "")
lbl_inst.pack()

lbl_fl_type = tk.Label(sec_frm, text="Flex Load Type:")
lbl_fl_type.pack(pady=10)
cb_fl_type = ttk.Combobox(
    sec_frm,
    values=fl_types[1:],
    state="readonly"
)
cb_fl_type.set("Type of Flex Load")
cb_fl_type.pack(anchor="center")

cb_fl_type.bind("<<ComboboxSelected>>", update_reg_options)

options_frame = ttk.Frame(sec_frm)
options_frame.pack(fill="x", pady=(10, 0))

root.mainloop()
