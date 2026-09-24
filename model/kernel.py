from dataclasses import dataclass
from engine import System, Signal, Engine, drive

@dataclass
class Kernel(System):
    def boot(self, sig: Signal):
        print("boot")
        sig.engine.emit(self, "setup")

    def setup(self, sig: Signal):
        print("kernel::setup")
        earlycon = EarlyCon()
        drive(earlycon, "setup")


@dataclass
class EarlyCon(System):
    def setup(self, sig: Signal):
        print("earlycon::setup")
