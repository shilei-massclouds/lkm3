"""Kernel IO"""

from dataclasses import dataclass, field

from framework.contention import TRANSPARENT_CV
from framework.engine import Signal, System, visibility
from framework.sync_primitives import (
    GuardLocalIrq,
    GuardPreemption,
    GuardYieldTryLock,
)


@dataclass
class PrintkRecord(System):
    seq: int
    data: str = ""
    state: str = "reserved"

    def fill(self, sig: Signal):
        self.data = sig.args["msg"]

    def commit(self, sig: Signal):
        assert self.state == "reserved"
        self.state = "committed"

    def flush(self, sig: Signal):
        reset_id = sig.args["head_id"]
        con = sig.args["con"]
        if con.seq == self.seq:
            if self.state == "committed":
                self.drive(sig.env, con, "write", msg=self.data)
                con.seq += 1
            else:
                con.seq = reset_id


@dataclass
class PrintkRingBuffer(System):
    head_id: int = 0
    records: list[PrintkRecord] = field(default_factory=list)

    def __repr__(self):
        num = len(self.records)
        head = self.head_id
        return f"PrintkRingBuffer({num} records, head={head})"

    def store(self, sig: Signal):
        self.drive(sig.env, self, "reserve", msg=sig.args["msg"])

    def reserve(self, sig: Signal):
        rid = self.head_id
        self.records.append(PrintkRecord(rid))
        self.head_id += 1
        sig.chain(self, "fill", rid=rid, msg=sig.args["msg"])

    def fill(self, sig: Signal):
        rid = sig.args["rid"]
        msg = sig.args["msg"]
        self.drive(sig.env, self.records[rid], "fill", msg=msg)
        sig.chain(self, "commit", rid=rid)

    def commit(self, sig: Signal):
        rid = sig.args["rid"]
        self.drive(sig.env, self.records[rid], "commit")

    def emit_next_record(self, sig: Signal):
        con = sig.args["con"]
        seq = con.seq
        self.drive_all(
            sig.env, self.records[seq:], "flush", con=con, head_id=self.head_id
        )


@dataclass
class Io(System):
    def __repr__(self):
        return "Io"

    @visibility(TRANSPARENT_CV)
    def printk(self, sig: Signal):
        from global_vars import gv

        with GuardLocalIrq(sig.env.cv):
            self.drive(sig.env, gv.prb, "store", msg=sig.args["msg"])

        with GuardPreemption(sig.env.cv), GuardYieldTryLock(sig.env.cv):
            self.drive(sig.env, gv.console_list, "flush_all")
