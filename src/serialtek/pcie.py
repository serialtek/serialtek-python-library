from enum import Enum


class PcieWidth(Enum):
    x1 = 0
    x2 = 1
    x4 = 2
    x8 = 3
    x12 = 4
    x16 = 5

    @property
    def lanes(self) -> int:
        """The number of lanes used"""
        match self:
            case PcieWidth.x1:
                return 1
            case PcieWidth.x2:
                return 2
            case PcieWidth.x4:
                return 4
            case PcieWidth.x8:
                return 8
            case PcieWidth.x12:
                return 12
            case PcieWidth.x16:
                return 16


class PcieSpeed(Enum):
    Gen1 = 0
    Gen2 = 1
    Gen3 = 2
    Gen4 = 3
    Gen5 = 4
    Gen6 = 5

    def __str__(self) -> str:
        match self:
            case PcieSpeed.Gen1:
                return "2.5 GT/s"
            case PcieSpeed.Gen2:
                return "5.0 GT/s"
            case PcieSpeed.Gen3:
                return "8.0 GT/s"
            case PcieSpeed.Gen4:
                return "16.0 GT/s"
            case PcieSpeed.Gen5:
                return "32.0 GT/s"
            case PcieSpeed.Gen6:
                return "64.0 GT/s"
