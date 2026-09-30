"""Console Device"""

from dataclasses import dataclass

from engine import Signal, System


@dataclass
class Console(System):
    ready: bool = False
    driver: str = ""

    def setup(self, sig: Signal):
        assert not self.ready
        self.ready = True
        self.driver = sig.args["drv"]
