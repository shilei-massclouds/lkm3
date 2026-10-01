"""Kernel IO"""

from dataclasses import dataclass

from engine import Signal, System


@dataclass
class PrintkRingBuffer(System):
    def store(self, sig: Signal):
        self.drive(self, "alloc")
        self.drive(self, "fill")
        self.drive(self, "commit")

    def alloc(self, sig: Signal):
        pass

    def fill(self, sig: Signal):
        pass

    def commit(self, sig: Signal):
        pass

    def get_next_record(self, sig: Signal):
        pass


@dataclass
class Io(System):
    def printk(self, sig: Signal):
        from global_vars import gv

        self.drive(gv.prb, "store")
        self.drive(gv.console_list, "flush_all")
