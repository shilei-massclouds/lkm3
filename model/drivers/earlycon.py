"""EarlyCon Device and EarlyCon DriverTable"""

from dataclasses import dataclass, field
from drivers.console import Console
from engine import Signal, System, drive, drive_all
from kernel.params import Param

@dataclass
class EarlyCon(System):
    console: Console = field(default_factory=Console)

    def setup(self, sig: Signal):
        drv_name = sig.args.get("drv")
        drive(self.console, "setup", drv=drv_name)


@dataclass
class EarlyConDrv(System):
    pass


@dataclass
class EarlyConDrvTable(System):
    table: list[EarlyConDrv] = field(default_factory=list)

    def register(self, sig: Signal):
        drv = sig.args.get("drv")
        self.table.append(drv)

    def probe(self, sig: Signal):
        drv = sig.args["drv"]
        drive_all(self.table, "setup", drv=drv)


@dataclass
class EarlyConParam(Param):
    def parse(self, sig: Signal):
        from global_vars import gv
        global gv
        drv = sig.args["val"]
        drive(gv.earlycon_driver_table, "probe", drv=drv)
