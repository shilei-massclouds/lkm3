"""Test printk ring-buffer synchronization boundaries."""

import pytest

from drivers.console import Console
from framework.contention import ContentionVector
from framework.engine import TaskLocalEnv
from framework.sync_primitives import (
    GuardYieldTryLock,
)
from kernel.io import PrintkRecord, PrintkRingBuffer
from systems.computer import Computer


def test_prb_record_emission_requires_console_protection():
    source = Computer()
    prb = PrintkRingBuffer()
    con = Console()
    env = TaskLocalEnv(ContentionVector.ones())

    with pytest.raises(AssertionError, match="Contention invariant violated"):
        source.drive(env, prb, "_emit_next_record", con=con)

    with GuardYieldTryLock(env.cv, Console):
        source.drive(env, prb, "_emit_next_record", con=con)


def test_printk_record_flush_requires_versioned_read_protection():
    source = Computer()
    record = PrintkRecord(0, data="message", state="committed")
    con = Console(seq=0)
    env = TaskLocalEnv(ContentionVector.ones())

    with GuardYieldTryLock(env.cv, Console):
        source.drive(env, record, "flush", con=con, head_id=1)

    assert con.seq == 1
