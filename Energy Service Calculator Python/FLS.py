# Supplemental file for Energy Service FLS calculation
# Calculates FLS from coefficients and normalized flex load

def getShiftScore(coefficients, NormFlexLoad):
    shiftScore = (
        coefficients[0] * NormFlexLoad.Shift.Power +
        coefficients[1] * NormFlexLoad.Shift.ShiftCategory +
        coefficients[2] * NormFlexLoad.Shift.ResponseTime +
        coefficients[3] * NormFlexLoad.Shift.PercentShift
    )
    print("Shift Score: ", shiftScore)
    return shiftScore

def getStorageScore(coefficients, NormFlexLoad):
    storageScore = (
        coefficients[4] * NormFlexLoad.Store.ECharge +
        coefficients[5] * NormFlexLoad.Store.EDischarge
    )
    print("Storage Score: ", storageScore)
    return storageScore

def getControlScore(coefficients, NormFlexLoad):
    cntrlScore = (
        coefficients[6] * int(NormFlexLoad.Control.CanSchedule) +
        coefficients[7] * int(NormFlexLoad.Control.AppExists) +
        coefficients[8] * int(NormFlexLoad.Control.WirelessConnection) +
        coefficients[9] * int(NormFlexLoad.Control.ToUData)
    )
    print("Control Score: ", cntrlScore)
    return cntrlScore

def getInteropScore(coefficients, NormFlexLoad):
    interopScore = (
        coefficients[10] * int(NormFlexLoad.Interop.OpenStandard) +
        coefficients[11] * int(NormFlexLoad.Interop.UCMDCMReady) +
        coefficients[12] * int(NormFlexLoad.Interop.Compliant) + 
        coefficients[13] * NormFlexLoad.Interop.DataConformant +
        coefficients[14] * NormFlexLoad.Interop.ShiftConformant
    )
    print("Interoperability Score: ", interopScore)
    return interopScore

def FlexLoadScore(coefficients, NormFlexLoad):
    FLS = (getShiftScore(coefficients, NormFlexLoad) + 
           getStorageScore(coefficients, NormFlexLoad) +
           getControlScore(coefficients, NormFlexLoad) +
           getInteropScore(coefficients, NormFlexLoad)
    )

    print("Flex Load Score: ", FLS)
    return FLS
