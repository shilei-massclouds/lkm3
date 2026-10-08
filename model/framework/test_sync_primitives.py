"""Test synchronization guards, domain adjustments and state restoration."""

import pytest

from framework.contention import ContentionVector
from framework.sync_primitives import (
    GuardBusyWaitLock,
    GuardLocalIrq,
    GuardPreemption,
    GuardYieldLock,
    GuardYieldTryLock,
)

DOMAINS = ("local_irq", "local_tasks", "remote_irq", "remote_tasks")


def test_irq_guard_restores_initial_state_without_reverting_other_domains():
    initial_irq = 1
    cv = ContentionVector(local_irq=initial_irq, remote_irq=0)

    with GuardLocalIrq(cv):
        assert cv.local_irq == 0
        assert cv.local_tasks == cv.remote_tasks == 1
        assert cv.remote_irq == 0
        cv.local_tasks = 0

    assert cv.local_irq == initial_irq
    assert cv.local_tasks == cv.remote_irq == 0
    assert cv.remote_tasks == 1


@pytest.mark.parametrize("local_tasks", [0, 1, 2])
def test_preemption_guard_restores_initial_state_without_changing_other_domains(
    local_tasks,
):
    cv = ContentionVector(
        local_irq=2,
        local_tasks=local_tasks,
        remote_irq=-1,
        remote_tasks=3,
    )

    with GuardPreemption(cv):
        assert cv.local_tasks == local_tasks - 1
        assert (cv.local_irq, cv.remote_irq, cv.remote_tasks) == (2, -1, 3)

    assert cv.local_tasks == local_tasks
    assert (cv.local_irq, cv.remote_irq, cv.remote_tasks) == (2, -1, 3)


def test_preemption_guard_restores_state_and_propagates_action_assertion():
    cv = ContentionVector.ones()

    with pytest.raises(AssertionError, match="action failed"), GuardPreemption(cv):
        assert cv.local_tasks == 0
        assert False, "action failed"

    assert cv.local_tasks == 1


def test_irq_guard_restores_state_and_propagates_action_assertion():
    initial_irq = 1
    cv = ContentionVector(local_irq=initial_irq)

    with pytest.raises(AssertionError, match="action failed"), GuardLocalIrq(cv):
        assert cv.local_irq == 0
        assert False, "action failed"

    assert cv.local_irq == initial_irq


def test_nested_irq_guards_restore_the_surrounding_irq_state():
    cv = ContentionVector.ones()

    with GuardLocalIrq(cv):
        with (
            pytest.raises(AssertionError, match="inner action failed"),
            GuardLocalIrq(cv),
        ):
            assert cv.local_irq == -1
            assert False, "inner action failed"
        assert cv.local_irq == 0

    assert cv.local_irq == 1


def test_redundant_irq_guards_allow_negative_levels_and_restore_exclusive_state():
    cv = ContentionVector.zeros()

    with GuardLocalIrq(cv):
        assert cv.local_irq == -1
        with GuardLocalIrq(cv):
            assert cv.local_irq == -2
        assert cv.local_irq == -1

    assert cv.local_irq == 0


@pytest.mark.parametrize("initial", [0, 1, 2])
def test_busy_wait_guard_preserves_local_contention_and_restores_remote_domains(
    initial,
):
    cv = ContentionVector(
        local_irq=initial,
        local_tasks=initial,
        remote_irq=initial,
        remote_tasks=initial,
    )

    with GuardBusyWaitLock(cv):
        assert cv.local_irq == initial
        assert cv.local_tasks == initial
        assert cv.remote_irq == initial - 1
        assert cv.remote_tasks == initial - 1

    assert all(getattr(cv, domain) == initial for domain in DOMAINS)


def test_busy_wait_guard_restores_state_and_propagates_action_assertion():
    cv = ContentionVector.ones()

    with pytest.raises(AssertionError, match="action failed"), GuardBusyWaitLock(cv):
        assert (cv.local_irq, cv.local_tasks, cv.remote_irq, cv.remote_tasks) == (
            1,
            1,
            0,
            0,
        )
        assert False, "action failed"

    assert all(getattr(cv, domain) == 1 for domain in DOMAINS)


@pytest.mark.parametrize("local_tasks, remote_tasks", [(1, 1), (0, 0), (2, 4)])
def test_nested_yield_lock_guards_restore_task_contention(local_tasks, remote_tasks):
    cv = ContentionVector(
        local_irq=0, local_tasks=local_tasks, remote_tasks=remote_tasks
    )

    with GuardYieldLock(cv):
        assert (cv.local_tasks, cv.remote_tasks) == (local_tasks - 1, remote_tasks - 1)
        assert (cv.local_irq, cv.remote_irq) == (0, 1)
        with GuardYieldLock(cv):
            assert (cv.local_tasks, cv.remote_tasks) == (
                local_tasks - 2,
                remote_tasks - 2,
            )
            assert (cv.local_irq, cv.remote_irq) == (0, 1)
        assert (cv.local_tasks, cv.remote_tasks) == (local_tasks - 1, remote_tasks - 1)

    assert (cv.local_tasks, cv.remote_tasks) == (local_tasks, remote_tasks)
    assert (cv.local_irq, cv.remote_irq) == (0, 1)


@pytest.mark.parametrize("guard_type", [GuardYieldLock, GuardYieldTryLock])
def test_yield_guard_restores_on_assertion_without_reverting_body_changes(guard_type):
    cv = ContentionVector.ones()

    with pytest.raises(AssertionError, match="action failed"), guard_type(cv):
        cv.remote_tasks += 2
        cv.local_irq -= 1
        assert False, "action failed"

    assert (cv.local_tasks, cv.remote_tasks) == (1, 3)
    assert (cv.local_irq, cv.remote_irq) == (0, 1)


@pytest.mark.parametrize("initial", [0, 1])
def test_nested_yield_try_lock_guards_restore_all_domains(initial):
    cv = ContentionVector(
        local_irq=initial,
        local_tasks=initial,
        remote_irq=initial,
        remote_tasks=initial,
    )

    with GuardYieldTryLock(cv):
        assert all(getattr(cv, domain) == initial - 1 for domain in DOMAINS)
        with GuardYieldTryLock(cv):
            assert all(getattr(cv, domain) == initial - 2 for domain in DOMAINS)
        assert all(getattr(cv, domain) == initial - 1 for domain in DOMAINS)

    assert all(getattr(cv, domain) == initial for domain in DOMAINS)
