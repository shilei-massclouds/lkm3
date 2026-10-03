"""EarlyCon Device and EarlyCon DriverTable"""

from dataclasses import dataclass, field

from drivers.console import Console
from engine import Signal, System
from kernel.params import Param


@dataclass
class EarlyCon(System):
    console: Console = field(default_factory=Console)

    def setup(self, sig: Signal):
        from global_vars import gv

        drv_name = sig.args.get("drv")
        self.drive(sig.engine.ce, self.console, "setup", drv=drv_name)
        self.drive(sig.engine.ce, gv.console_list, "register", con=self.console)


@dataclass
class EarlyConDrv(System):
    pass


@dataclass
class EarlyConDrvTable(System):
    table: list[EarlyConDrv] = field(default_factory=list)

    def register(self, sig: Signal):
        drv = sig.args["drv"]
        assert isinstance(drv, EarlyConDrv)
        self.table.append(drv)

    def probe(self, sig: Signal):
        drv = sig.args["drv"]
        self.drive_all(sig.engine.ce, self.table, "setup", drv=drv)


@dataclass
class EarlyConParam(Param):
    def parse(self, sig: Signal):
        from global_vars import gv

        if sig.args["key"] == "earlycon" and sig.args["early"]:
            val = sig.args["val"]
            self.drive(sig.engine.ce, gv.earlycon_driver_table, "probe", drv=val)
