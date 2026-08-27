import tkinter as tk
from tkinter import ttk
import xml.etree.ElementTree as ET
import os
from pathlib import Path
import platform
from tkinter import filedialog

VERSION = 2.0

script_dir = os.path.dirname(os.path.abspath(__file__))

my_vars = {}
cntrl_intop_reg_vars = {}

fl_types = ["Type of Flex Load",
            "Heat Pump Water Heater",
            "Electric Resistance Water Heater",
            "HVAC",
            "EV Charger",
            "Dryer",
            "Battery",
            "Generic"]

# regulation variables
hpwh_reg = ["HPWH Model", 
            "Compressor Power [W]",
            "Resistance Element Power [W]",
            "Tank Volume [gal]",
            "Maximum Water Temperature [°F]",
            "Minimum Water Temperature [°F]",
            "COP or UEF",
            "Heating Capacity [BTU/hr]",
            "Response Time [s]",
            "Control Interval [s]"]
erwh_reg = ["ERWH Model",
            "Heating Element Power [W]"
            "Tank Volume [gal]",
            "Maximum Water Temperature [°F]",
            "Minimum Water Temperature [°F]",
            "Heating Capacity [BTU/hr]",
            "Response Time [s]",
            "Control Interval [s]"]
hvac_reg = ["HVAC Model",
            "Heating Capacity [BTU/hr]",
            "Cooling Capacity [BTU/hr]",
            "Minimum Modulation [%]",
            "Maximum Indoor Temperature [°F]",
            "Minimum Indoor Temperature [°F]",
            "Response Time [s]",
            "Control Interval [s]",
            "Effective Building Thermal Capacity [kWh/°F]"]
ev_reg = ["EV Model",
            "Rated Charging Power [kW]",
            "Maximum Battery Capacity [kWh]",
            "Usable Battery Flexibility [%]",
            "Charging Efficiency [%]",
            "Response Time [s]",
            "Control Interval [s]"]
dryer_reg = ["Dryer Model",
            "Rated Power [kW]",
            "Cycle Energy [kWh]",
            "Typical Cycle Duration [min]",
            "Maximum Deferral Time [min]",
            "Response Time [s]",
            "Control Interval [s]"]
batt_reg = ["Battery Model",
            "Rated Power [kW]",
            "Usable Energy Capacity [kWh]",
            "State of Charge Operating Range [%]",
            "Response Time [s]",
            "Control Interval [s]",
            "Recharge/Recovery Rate [kW]"]
gen_reg = ["Generic Model",
            "Total Power [W]",
            "Regulation Capacity [kWh]",
            "Continuous Regulation Duration [min]",
            "Response Time [s]",
            "Recovery Time [s]",
            "Control Interval [s]"]

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
    for widget in options_frame.winfo_children():
        widget.destroy()

    selected = cb_fl_type.get()

    if selected == "Heat Pump Water Heater":
        my_vars[hpwh_reg[0]] = tk.StringVar()
        for i in range(1, len(hpwh_reg)):
            my_vars[hpwh_reg[i]] = tk.DoubleVar()
    elif selected == "Electric Resistance Water Heater":
        my_vars[erwh_reg[0]] = tk.StringVar()
        for i in range(1, len(erwh_reg)):
            my_vars[erwh_reg[i]] = tk.DoubleVar()
    elif selected == "HVAC":
        my_vars[hvac_reg[0]] = tk.StringVar()
        for i in range(1, len(hvac_reg)):
            my_vars[hvac_reg[i]] = tk.DoubleVar()
    elif selected == "EV Charger":
        my_vars[ev_reg[0]] = tk.StringVar()
        for i in range(1, len(ev_reg)):
            my_vars[ev_reg[i]] = tk.DoubleVar()
    elif selected == "Dryer":
        my_vars[dryer_reg[0]] = tk.StringVar()
        for i in range(1, len(dryer_reg)):
            my_vars[dryer_reg[i]] = tk.DoubleVar()
    elif selected == "Battery":
        my_vars[batt_reg[0]] = tk.StringVar()
        for i in range(1, len(batt_reg)):
            my_vars[batt_reg[i]] = tk.DoubleVar()
    elif selected == "Generic":
        my_vars[gen_reg[0]] = tk.StringVar()
        for i in range(1, len(gen_reg)):
            my_vars[gen_reg[i]] = tk.DoubleVar()

    show_options()
    cntrl_intop_reg()
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

# make the xml file
def make_xml():
    if cb_fl_type.get() == "Heat Pump Water Heater":
        xml_root = ET.Element("HPWH")
    elif cb_fl_type.get() == "Electric Resistance Water Heater":
        xml_root = ET.Element("ERWH")
    elif cb_fl_type.get() == "HVAC":
        xml_root = ET.Element("HVAC")
    elif cb_fl_type.get() == "EV Charger":
        xml_root = ET.Element("EV")
    elif cb_fl_type.get() == "Dryer":
        xml_root = ET.Element("Dryer")
    elif cb_fl_type.get() == "Battery":
        xml_root = ET.Element("Battery")
    elif cb_fl_type.get() == "Generic":
        xml_root = ET.Element("Generic")
    else:
        top = tk.Toplevel()
        top.title("Invalid Flex Load Type")
        top.geometry("200x75")
        lbl_ok = tk.Label(top, text="Please select a valid flex load type")
        lbl_ok.pack()
        but_ok = tk.Button(top, text="Okay", command=top.destroy)
        but_ok.pack()

    # output folder will be in specified folder, in new folder labled type of flex load
    # ie user selects hpwh and desktop folder:
    #   created hpwh xml will be in "Heat Pump Water Heater" folder in desktop
    #   xml name will be model number of hpwh
    out_dir = filedialog.askdirectory(
        title="Please Select Output Folder",
        initialdir="/")

    OUT_FOLD = str(cb_fl_type.get())
    OUT_PATH = os.path.join(out_dir, OUT_FOLD)

    final_vars = my_vars | cntrl_intop_reg_vars
    vars_keys = list(final_vars.keys())

    ET.SubElement(xml_root, "DeviceModel").text = final_vars[vars_keys[0]].get()
    ET.SubElement(xml_root, "Version").text = str(VERSION)

    # regulation variable xml section
    reg = ET.SubElement(xml_root, "RegVars")
    for i in range(1, len(vars_keys)):
        ET.SubElement(reg, vars_keys[i]).text = final_vars[vars_keys[i]].get()

    # set up the xml file
    tree = ET.ElementTree(xml_root)

    # check if the directory exists, if not, make it
    if not Path(OUT_PATH).is_dir():
        Path(OUT_PATH).mkdir(parents=True, exist_ok=True)
    
    output_pathname = os.path.join(OUT_PATH, f"{final_vars[vars_keys[0]].get()}.xml")
    tree.write(output_pathname, encoding="utf-8", xml_declaration=True)

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


def cntrl_intop_reg():
    cntrl_intop_reg_vars["sched"] = tk.BooleanVar()
    cntrl_intop_reg_vars["app"] = tk.BooleanVar()
    cntrl_intop_reg_vars["wireless"] = tk.BooleanVar()
    cntrl_intop_reg_vars["tou"] = tk.BooleanVar()
    cntrl_intop_reg_vars["std"] = tk.BooleanVar()
    cntrl_intop_reg_vars["ucm"] = tk.BooleanVar()
    cntrl_intop_reg_vars["cmplnt"] = tk.BooleanVar()
    cntrl_intop_reg_vars["data"] = tk.DoubleVar()
    cntrl_intop_reg_vars["shift"] = tk.DoubleVar()

    cbut_sc("Can Schedule?", cntrl_intop_reg_vars["sched"])
    cbut_sc("App Exists?", cntrl_intop_reg_vars["app"])
    cbut_sc("Wireless Connection?", cntrl_intop_reg_vars["wireless"])
    cbut_sc("Connect to ToU Data?", cntrl_intop_reg_vars["tou"])
    cbut_sc("Open Standard?", cntrl_intop_reg_vars["std"])
    cbut_sc("UCM/DCM Ready?", cntrl_intop_reg_vars["ucm"])
    cbut_sc("Compliant?", cntrl_intop_reg_vars["cmplnt"])
    entry_sc("Data Conformant?", cntrl_intop_reg_vars["data"])
    entry_sc("Shift Conformant?", cntrl_intop_reg_vars["shift"])


def show_options():
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
    values=fl_types,
    state="readonly"
)
cb_fl_type.set("Type of Flex Load")
cb_fl_type.pack(anchor="center")

cb_fl_type.bind("<<ComboboxSelected>>", update_reg_options)

options_frame = ttk.Frame(sec_frm)
options_frame.pack(fill="x", pady=(10, 0))

root.mainloop()