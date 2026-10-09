"""EarlyCon Device and EarlyCon DriverTable"""

from dataclasses import dataclass, field

from drivers.console import Console
from framework.engine import Signal, System
from kernel.params import Param


@dataclass
class EarlyCon(System):
    console: Console = field(default_factory=Console)

    def _setup(self, sig: Signal):
        from global_vars import gv

        drv_name = sig.args.get("drv")
        self.drive(sig.env, self.console, "_setup", drv=drv_name)
        self.drive(sig.env, gv.console_list, "_register", con=self.console)


@dataclass
class EarlyConDrv(System):
    pass


@dataclass
class EarlyConDrvTable(System):
    table: list[EarlyConDrv] = field(default_factory=list)

    def _register(self, sig: Signal):
        drv = sig.args["drv"]
        assert isinstance(drv, EarlyConDrv)
        self.table.append(drv)

    def _probe(self, sig: Signal):
        drv = sig.args["drv"]
        self.drive_all(sig.env, self.table, "_setup", drv=drv)


@dataclass
class EarlyConParam(Param):
    def _parse(self, sig: Signal):
        from global_vars import gv

        if sig.args["key"] == "earlycon" and sig.args["early"]:
            val = sig.args["val"]
            self.drive(sig.env, gv.earlycon_driver_table, "_probe", drv=val)
