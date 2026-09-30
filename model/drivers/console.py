"""Console Device"""

from dataclasses import dataclass

from engine import Signal, System


@dataclass
class Console(System):
    ready: bool = False

    def setup(self, sig: Signal):
        assert not self.ready
        self.ready = True

        drv_name = sig.args.get("drv")
        print(f"EarlyCon is ready with '{drv_name}'")
