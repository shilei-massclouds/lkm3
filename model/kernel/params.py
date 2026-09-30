"""Kernel Params"""

from dataclasses import dataclass, field

from engine import Signal, System, drive, drive_all


@dataclass
class Param(System):
    pass


@dataclass
class ParamTable(System):
    table: list[Param] = field(default_factory=list)

    def register(self, sig: Signal):
        param = sig.args.get("param")
        assert isinstance(param, Param)
        self.table.append(param)

    def parse(self, sig: Signal):
        key = sig.args["key"]
        val = sig.args["val"]
        early = sig.args["early"]
        drive_all(self.table, "parse", key=key, val=val, early=early)


@dataclass(init=False)
class CmdItem(System):
    key: str
    val: str

    def __init__(self, key: str, val: str):
        self.key = key
        self.val = val

    def parse(self, sig: Signal):
        from global_vars import gv

        early = sig.args["early"]
        drive(gv.kernel_param_table, "parse", key=self.key, val=self.val, early=early)


@dataclass
class CmdLine(System):
    items: list[CmdItem] = field(default_factory=list)

    def add(self, sig: Signal):
        item = CmdItem(sig.args["key"], sig.args["val"])
        self.items.append(item)

    def parse(self, sig: Signal):
        early = sig.args["early"]
        drive_all(self.items, "parse", early=early)
