"""Test printk ring-buffer synchronization boundaries."""

import pytest

from drivers.console import Console
from framework.contention import ContentionVector
from framework.engine import TaskLocalEnv
from framework.sync_primitives import GuardYieldTryLock
from kernel.io import PrintkRingBuffer
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
