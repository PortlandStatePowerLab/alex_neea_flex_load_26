# Main code for calculating Energy Service FLS
# Relies on:
#     FLS.py
#     flexload.py
#     importflexload.py -- currently not working because xml import function is unimplimented (7/7/26)

import flexload as fl
import FLS as fls
import importflexload as impfl

# Set initial metric coefficients - can be changed by user
MetricCoefficients = [
    5, #A
    1.75, #B
    0.75, #C
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


def compareToIdeal():
    if impfl.InputFlexLoad.Control.CanSchedule == fl.IdealFlexLoad.Control.CanSchedule:
        normSched = True
    else:
        normSched = False
    
    if impfl.InputFlexLoad.Control.AppExists == fl.IdealFlexLoad.Control.AppExists:
        normApp = True
    else:
        normApp = False

    if impfl.InputFlexLoad.Control.WirelessConnection == fl.IdealFlexLoad.Control.WirelessConnection:
        normWireless = True
    else:
        normWireless = False
    
    if impfl.InputFlexLoad.Control.ToUData == fl.IdealFlexLoad.Control.ToUData:
        normToU = True
    else:
        normToU = False
    
    if impfl.InputFlexLoad.Interop.OpenStandard == fl.IdealFlexLoad.Interop.OpenStandard:
        normOpenStd = True
    else:
        normOpenStd = False
    
    if impfl.InputFlexLoad.Interop.UCMDCMReady == fl.IdealFlexLoad.Interop.UCMDCMReady:
        normUCMDCM = True
    else:
        normUCMDCM = False
    
    if impfl.InputFlexLoad.Interop.Compliant == fl.IdealFlexLoad.Interop.Compliant:
        normCompliant = True
    else:
        normCompliant = False

    global NormFlexLoad 
    NormFlexLoad = fl.FlexLoad(
        Shift = fl.ShiftPotential(
            impfl.InputFlexLoad.Shift.Power/fl.IdealFlexLoad.Shift.Power, 
            impfl.InputFlexLoad.Shift.ShiftCategory/fl.IdealFlexLoad.Shift.ShiftCategory, 
            (impfl.InputFlexLoad.Shift.ResponseTime - 120)/(fl.IdealFlexLoad.Shift.ResponseTime - 120), 
            impfl.InputFlexLoad.Shift.PercentShift/fl.IdealFlexLoad.Shift.PercentShift,
            ),
        Store = fl.Storage(
            impfl.InputFlexLoad.Store.ECharge/fl.IdealFlexLoad.Store.ECharge,
            impfl.InputFlexLoad.Store.EDischarge/fl.IdealFlexLoad.Store.EDischarge,
        ),
        Control = fl.Controllability(
            normSched,
            normApp,
            normWireless,
            normToU,
        ),
        Interop = fl.Interoperability(
            normOpenStd,
            normUCMDCM,
            normCompliant,
            impfl.InputFlexLoad.Interop.DataConformant/fl.IdealFlexLoad.Interop.DataConformant,
            impfl.InputFlexLoad.Interop.ShiftConformant/fl.IdealFlexLoad.Interop.ShiftConformant,
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

def main():
    print("Would you like to import a flex load file? [y/n]")
    importquestion = input()
    if importquestion.lower() == "y":
        impfl.readFlexLoad()
    else:
        impfl.inputFlexLoad()

    print("Would you like to input metric coefficients? [y/n]")
    coeffquest = input()
    if coeffquest.lower() == "y":
        changeCoeff(MetricCoefficients)

    compareToIdeal()

    fls.FlexLoadScore(MetricCoefficients, NormFlexLoad)


main()
