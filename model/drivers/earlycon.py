"""EarlyCon Device and EarlyCon DriverTable"""

from dataclasses import dataclass, field
from drivers.console import Console
from engine import Signal, System, drive, drive_all

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
        dev = sig.args.get("dev")
        drv_type = sig.args.get("drv_type")
        drive_all(self.table, "setup", drv_type=drv_type, dev=dev)
