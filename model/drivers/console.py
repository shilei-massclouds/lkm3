"""Console Device"""

from dataclasses import dataclass, field

from engine import Signal, System


@dataclass
class Console(System):
    ready: bool = False
    driver: str = ""
    seq: int = 0

    def setup(self, sig: Signal):
        assert not self.ready
        self.ready = True
        self.driver = sig.args["drv"]

    def emit_next_record(self, sig: Signal):
        from global_vars import gv

        self.drive(gv.prb, "get_next_record", seq=self.seq)
        self.drive(self, "write")
        self.seq += 1

    def write(self, sig: Signal):
        pass


@dataclass
class ConsoleList(System):
    items: list[Console] = field(default_factory=list)

    def register(self, sig: Signal):
        from global_vars import gv

        con = sig.args["con"]
        self.items.append(con)
        self.drive(gv.io, "printk")  # trigger flush prb

    def flush_all(self, sig: Signal):
        self.drive_all(self.items, "emit_next_record")
