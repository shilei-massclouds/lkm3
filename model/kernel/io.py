"""Kernel IO"""

from dataclasses import dataclass, field

from drivers.console import Console
from framework.contention import TASKPRIVATE_CV, TRANSPARENT_CV
from framework.engine import Signal, System, visibility
from framework.sync_primitives import (
    GuardAtomicReserve,
    GuardLocalIrq,
    GuardPreemption,
    GuardRcuReadSide,
    GuardYieldTryLock,
)


@visibility(TASKPRIVATE_CV)
@dataclass
class PrintkRecord(System):
    seq: int
    data: str = ""
    state: str = "reserved"

    def _fill(self, sig: Signal):
        self.data = sig.args["msg"]

    def _commit(self, sig: Signal):
        assert self.state == "reserved"
        self.state = "committed"

    def _flush(self, sig: Signal):
        reset_id = sig.args["head_id"]
        con = sig.args["con"]
        if con.seq == self.seq:
            if self.state == "committed":
                self.drive(sig.env, con, "_write", msg=self.data)
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

    def reserve(self, sig: Signal) -> PrintkRecord:
        with GuardAtomicReserve(sig.env.cv, self):
            return self.drive(sig.env, self, "_reserve")

    def _reserve(self, sig: Signal) -> PrintkRecord:
        rid = self.head_id
        record = PrintkRecord(rid)
        self.records.append(record)
        self.head_id += 1
        return record

    @visibility(TRANSPARENT_CV)
    def _emit_next_record(self, sig: Signal):
        con = sig.args["con"]
        seq = con.seq
        self.drive_all(
            sig.env, self.records[seq:], "_flush", con=con, head_id=self.head_id
        )


@dataclass
class Io(System):
    def __repr__(self):
        return "Io"

    def printk(self, sig: Signal):
        from global_vars import gv

        self.drive(sig.env, self, "vprintk_store", msg=sig.args["msg"])

        # Protect console instances while traversing the RCU-published list.
        with GuardPreemption(sig.env.cv):  # noqa: SIM117
            with GuardYieldTryLock(sig.env.cv, Console):
                with GuardRcuReadSide(sig.env.cv, gv.console_list):
                    self.drive(sig.env, gv.console_list, "_flush_all")

    def vprintk_store(self, sig: Signal):
        from global_vars import gv

        with GuardLocalIrq(sig.env.cv):  # noqa: SIM117
            with self.drive(sig.env, gv.prb, "reserve") as record:
                self.drive(sig.env, record, "_fill", msg=sig.args["msg"])
                self.drive(sig.env, record, "_commit")
