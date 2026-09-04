# File containing definition of class FlexLoad
# with subclasses ShiftPotential, Storage, Controllability, and Interoperability
# Also contains definition of an ideal flex load

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
