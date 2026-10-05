"""Console Device"""

from dataclasses import dataclass, field

from framework.engine import Signal, System


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

        self.drive(sig.env, gv.prb, "emit_next_record", con=self)

    def write(self, sig: Signal):
        print(f"=== Stdout: {sig.args['msg']} ===")


@dataclass
class ConsoleList(System):
    items: list[Console] = field(default_factory=list)

    def __repr__(self):
        num = len(self.items)
        return f"ConsoleList[{num} item(s)]"

    def register(self, sig: Signal):
        from global_vars import gv

        con = sig.args["con"]
        self.items.append(con)
        msg = f"console[{con.driver}]: enabled."
        self.drive(sig.env, gv.io, "printk", msg=msg)  # trigger flush prb

    def flush_all(self, sig: Signal):
        self.drive_all(sig.env, self.items, "emit_next_record")
