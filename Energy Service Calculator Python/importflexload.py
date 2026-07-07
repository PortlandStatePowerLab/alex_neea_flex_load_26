# NOT WORKING
# function readflexload(), for importing flex load values from an xml file, is currently (7/7/26) unimplimented
# Allows user to manually import flex load characteristics or import an xml file with the flex load characteristics

import flexload as fl

def inputFlexLoad():
    print("Please input flex load characteristics:")

    print("Shift Potential Characteristics:")
    print("Please input power [kW]:")
    inputPower = float(input())
    print("Please input shift category [0-3]")
    inputShiftCat = float(input())
    if inputShiftCat > 3 or inputShiftCat < 0:
        print("Please input a valid value for shift category [1-3]:")
        inputShiftCat = float(input())
    print("Please input response time [s]:")
    inputResponseTime = float(input())
    print("Please input percent shift [0-100]:")
    inputPercentShift = float(input())
    if inputPercentShift > 100 or inputPercentShift < 0:
        print("please input a valid percent shift [0-100]:")
        inputPercentShift = float(input())
    
    print("Please input storage characteristics:")
    print("Please input chargeable energy [kWh]:")
    inputECharge = float(input())
    print("Please input dischargeable energy [kWh]:")
    inputEDischarge = float(input())

    print("Please input control characteristics:")
    print("Please input if scheduling is available [y/n]:")
    temp = input()
    if temp == "y":
        inputCanSchedule = True
    elif temp == "n":
        inputCanSchedule = False
    print("Please input if an app exists [y/n]:")
    temp = input()
    if temp == "y":
        inputApp = True
    elif temp == "n":
        inputApp = False
    print("Please input if wireless connection is supported [y/n]")
    temp = input()
    if temp == "y":
        inputWireless = True
    elif temp == "n":
        inputWireless = False
    print("Please input if device can connect to ToU data [y/n]:")
    temp = input()
    if temp == "y":
        inputToU = True
    elif temp == "n":
        inputToU = False

    print("Please input interoperability characteristics:")
    print("Please input if device is open standard [y/n]:")
    temp = input()
    if temp == "y":
        inputOpenStd = True
    elif temp == "n":
        inputOpenStd = False
    print("Please input if device is UCM/DCM ready [y/n]:")
    temp = input()
    if temp == "y":
        inputUCMDCM = True
    elif temp == "n":
        inputUCMDCM = False
    print("Please input if device is compliant with communications and operational standards [y/n]:")
    temp = input()
    if temp == "y":
        inputCompliant = True
    elif temp == "n":
        inputCompliant = False
    print("Please intput how data conformant device is [0,1]:")
    inputDataCnfmt = float(input())
    print("Please input how shift conformant device is [0,1]:")
    inputShiftCnfmt = float(input())

    global InputFlexLoad 
    InputFlexLoad = fl.FlexLoad(
        Shift = fl.ShiftPotential(
            inputPower, 
            inputShiftCat, 
            inputResponseTime, 
            inputPercentShift,
            ),
        Store = fl.Storage(
            inputECharge,
            inputEDischarge,
        ),
        Control = fl.Controllability(
            inputCanSchedule,
            inputApp,
            inputWireless,
            inputToU,
        ),
        Interop = fl.Interoperability(
            inputOpenStd,
            inputUCMDCM,
            inputCompliant,
            inputDataCnfmt,
            inputShiftCnfmt,
        ),
    )


def readflexload():






# def readFlexLoad():
#     print("Please input flex load characteristics file name:")
#     filename = input()
#     with open(filename) as file:
#         templist = [line.strip() for line in file]
    
#     global InputFlexLoad 
#     InputFlexLoad = fl.FlexLoad(
#         Shift = fl.ShiftPotential(
#             float(templist[0]), 
#             float(templist[1]), 
#             float(templist[2]), 
#             float(templist[3]),
#             ),
#         Store = fl.Storage(
#             float(templist[4]),
#             float(templist[5]),
#         ),
#         Control = fl.Controllability(
#             bool(templist[6]),
#             bool(templist[7]),
#             bool(templist[8]),
#             bool(templist[9]),
#         ),
#         Interop = fl.Interoperability(
#             bool(templist[10]),
#             bool(templist[11]),
#             bool(templist[12]),
#             float(templist[13]),
#             float(templist[14]),
#         ),
#     )
