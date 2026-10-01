"""Console Device"""

from dataclasses import dataclass, field

from engine import Signal, System


@dataclass
class Console(System):
    ready: bool = False
    driver: str = ""

    def setup(self, sig: Signal):
        assert not self.ready
        self.ready = True
        self.driver = sig.args["drv"]


@dataclass
class ConsoleList(System):
    items: list[Console] = field(default_factory=list)

    def register(self, sig: Signal):
        con = sig.args["con"]
        self.items.append(con)
