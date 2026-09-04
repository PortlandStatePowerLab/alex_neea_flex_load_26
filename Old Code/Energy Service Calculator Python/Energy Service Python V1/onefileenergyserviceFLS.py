# As of 7/7/26, this code is the same as the separate file versions (FLS, energyserviceFLS, flexload, and importflexload)
# EXCEPT for the readFlexLoad function, which expects a file consisting only of the flex load values - no descriptions/lables - separated by new lines

from dataclasses import dataclass

@dataclass
class ShiftPotential:
    Power: float
    ShiftCategory: float
    ResponseTime: float
    PercentShift: float

@dataclass
class Storage:
    ECharge: float
    EDischarge: float

@dataclass
class Controllability:
    CanSchedule: bool
    AppExists: bool
    WirelessConnection: bool
    ToUData: bool

@dataclass
class Interoperability:
    OpenStandard: bool
    UCMDCMReady: bool
    Compliant: bool
    DataConformant: float
    ShiftConformant: float

class FlexLoad:
    def __init__(self, Shift, Store, Control, Interop):
        self.Shift = Shift
        self.Store = Store
        self.Control = Control
        self.Interop = Interop

    
IdealFlexLoad = FlexLoad(
    Shift = ShiftPotential(
        Power = 10.5,
        ShiftCategory = 3,
        ResponseTime = 0.1,
        PercentShift = 100,
    ),
    Store = Storage(
        ECharge = 70,
        EDischarge = 70,
    ),
    Control = Controllability(
        CanSchedule = True,
        AppExists = True,
        WirelessConnection = True,
        ToUData = True,
    ),
    Interop = Interoperability(
        OpenStandard = True,
        UCMDCMReady = True,
        Compliant = True,
        DataConformant = 1,
        ShiftConformant = 1,
    ),
)

MetricCoefficients = [
    5, #A
    1.75, #B
    0.25, #C
    3, #D
    5, #E
    5, #F
    1, #G
    1.5, #h
    4, #I
    3.5, #J
    1, #K
    1, #L
    2, #M
    2, #N
    4 #O
]



def readFlexLoad():
    print("Please input flex load characteristics file name:")
    filename = input()
    with open(filename) as file:
        templist = [line.strip() for line in file]
    
    global InputFlexLoad 
    InputFlexLoad = FlexLoad(
        Shift = ShiftPotential(
            float(templist[0]), 
            float(templist[1]), 
            float(templist[2]), 
            float(templist[3]),
            ),
        Store = Storage(
            float(templist[4]),
            float(templist[5]),
        ),
        Control = Controllability(
            bool(templist[6]),
            bool(templist[7]),
            bool(templist[8]),
            bool(templist[9]),
        ),
        Interop = Interoperability(
            bool(templist[10]),
            bool(templist[11]),
            bool(templist[12]),
            float(templist[13]),
            float(templist[14]),
        ),
    )



    

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
    InputFlexLoad = FlexLoad(
        Shift = ShiftPotential(
            inputPower, 
            inputShiftCat, 
            inputResponseTime, 
            inputPercentShift,
            ),
        Store = Storage(
            inputECharge,
            inputEDischarge,
        ),
        Control = Controllability(
            inputCanSchedule,
            inputApp,
            inputWireless,
            inputToU,
        ),
        Interop = Interoperability(
            inputOpenStd,
            inputUCMDCM,
            inputCompliant,
            inputDataCnfmt,
            inputShiftCnfmt,
        ),
    )


def compareToIdeal():
    if InputFlexLoad.Control.CanSchedule == IdealFlexLoad.Control.CanSchedule:
        normSched = True
    else:
        normSched = False
    
    if InputFlexLoad.Control.AppExists == IdealFlexLoad.Control.AppExists:
        normApp = True
    else:
        normApp = False

    if InputFlexLoad.Control.WirelessConnection == IdealFlexLoad.Control.WirelessConnection:
        normWireless = True
    else:
        normWireless = False
    
    if InputFlexLoad.Control.ToUData == IdealFlexLoad.Control.ToUData:
        normToU = True
    else:
        normToU = False
    
    if InputFlexLoad.Interop.OpenStandard == IdealFlexLoad.Interop.OpenStandard:
        normOpenStd = True
    else:
        normOpenStd = False
    
    if InputFlexLoad.Interop.UCMDCMReady == IdealFlexLoad.Interop.UCMDCMReady:
        normUCMDCM = True
    else:
        normUCMDCM = False
    
    if InputFlexLoad.Interop.Compliant == IdealFlexLoad.Interop.Compliant:
        normCompliant = True
    else:
        normCompliant = False

    global NormFlexLoad 
    NormFlexLoad = FlexLoad(
        Shift = ShiftPotential(
            InputFlexLoad.Shift.Power/IdealFlexLoad.Shift.Power, 
            InputFlexLoad.Shift.ShiftCategory/IdealFlexLoad.Shift.ShiftCategory, 
            (InputFlexLoad.Shift.ResponseTime - 120)/(IdealFlexLoad.Shift.ResponseTime - 120), 
            InputFlexLoad.Shift.PercentShift/IdealFlexLoad.Shift.PercentShift,
            ),
        Store = Storage(
            InputFlexLoad.Store.ECharge/IdealFlexLoad.Store.ECharge,
            InputFlexLoad.Store.EDischarge/IdealFlexLoad.Store.EDischarge,
        ),
        Control = Controllability(
            normSched,
            normApp,
            normWireless,
            normToU,
        ),
        Interop = Interoperability(
            normOpenStd,
            normUCMDCM,
            normCompliant,
            InputFlexLoad.Interop.DataConformant/IdealFlexLoad.Interop.DataConformant,
            InputFlexLoad.Interop.ShiftConformant/IdealFlexLoad.Interop.ShiftConformant,
        ),
    )


def changeCoeff(coefficients):
    letters = "ABCDEFGHIJKLMNO"

    for i in range(len(coefficients)):
        while True:
            try:
                coefficients[i] = float(input(f"Please input coefficient {letters[i]}: "))
                break
            except ValueError:
                print("Please enter a valid number.")

    return coefficients

def getShiftScore(coefficients):
    shiftScore = (
        coefficients[0] * NormFlexLoad.Shift.Power +
        coefficients[1] * NormFlexLoad.Shift.ShiftCategory +
        coefficients[2] * NormFlexLoad.Shift.ResponseTime +
        coefficients[3] * NormFlexLoad.Shift.PercentShift
    )
    print("Shift Score: ", shiftScore)
    return shiftScore

def getStorageScore(coefficients):
    storageScore = (
        coefficients[4] * NormFlexLoad.Store.ECharge +
        coefficients[5] * NormFlexLoad.Store.EDischarge
    )
    print("Storage Score: ", storageScore)
    return storageScore

def getControlScore(coefficients):
    cntrlScore = (
        coefficients[6] * int(NormFlexLoad.Control.CanSchedule) +
        coefficients[7] * int(NormFlexLoad.Control.AppExists) +
        coefficients[8] * int(NormFlexLoad.Control.WirelessConnection) +
        coefficients[9] * int(NormFlexLoad.Control.ToUData)
    )
    print("Control Score: ", cntrlScore)
    return cntrlScore

def getInteropScore(coefficients):
    interopScore = (
        coefficients[10] * int(NormFlexLoad.Interop.OpenStandard) +
        coefficients[11] * int(NormFlexLoad.Interop.UCMDCMReady) +
        coefficients[12] * int(NormFlexLoad.Interop.Compliant) + 
        coefficients[13] * NormFlexLoad.Interop.DataConformant +
        coefficients[14] * NormFlexLoad.Interop.ShiftConformant
    )
    print("Interoperability Score: ", interopScore)
    return interopScore

def FlexLoadScore(coefficients):
    FLS = (getShiftScore(coefficients) + 
           getStorageScore(coefficients) +
           getControlScore(coefficients) +
           getInteropScore(coefficients)
    )

    print("Flex Load Score: ", FLS)
    return FLS



def main():
    print("Would you like to import a flex load file? [y/n]")
    importquestion = input()
    if importquestion.lower() == "y":
        readFlexLoad()
    else:
        inputFlexLoad()

    print("Would you like to input metric coefficients? [y/n]")
    coeffquest = input()
    if coeffquest.lower() == "y":
        changeCoeff(MetricCoefficients)

    compareToIdeal()

    FlexLoadScore(MetricCoefficients)







main()
