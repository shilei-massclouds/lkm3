"""Test synchronization guards, domain adjustments and state restoration."""

import pytest

from framework.contention import ContentionVector
from framework.sync_primitives import (
    BusyWaitIrqSave,
    BusyWaitIrqSavePreemption,
    BusyWaitLock,
    GuardBusyWaitIrqSave,
    GuardBusyWaitIrqSavePreemption,
    GuardBusyWaitLock,
    GuardBusyWaitPreemption,
    GuardLocalIrq,
    GuardPreemption,
    GuardYieldLock,
    GuardYieldTryLock,
    LocalIrq,
    LocalMultiTasks,
    Preemption,
    RemoteCpus,
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

    with GuardBusyWaitLock(cv, object()):
        assert cv.local_irq == initial
        assert cv.local_tasks == initial
        assert cv.remote_irq == initial - 1
        assert cv.remote_tasks == initial - 1

    assert all(getattr(cv, domain) == initial for domain in DOMAINS)


def test_busy_wait_guard_restores_state_and_propagates_action_assertion():
    cv = ContentionVector.ones()

    with (
        pytest.raises(AssertionError, match="action failed"),
        GuardBusyWaitLock(cv, object()),
    ):
        assert (cv.local_irq, cv.local_tasks, cv.remote_irq, cv.remote_tasks) == (
            1,
            1,
            0,
            0,
        )
        assert False, "action failed"

    assert all(getattr(cv, domain) == 1 for domain in DOMAINS)


@pytest.mark.parametrize("lock_type", [BusyWaitIrqSave, BusyWaitIrqSavePreemption])
@pytest.mark.parametrize("initial_irq", [-1, 0, 1])
def test_busy_wait_irq_flags_are_independent_for_nested_acquisitions(
    lock_type, initial_irq
):
    cv = ContentionVector(local_irq=initial_irq)
    lock = lock_type(object())

    outer_flags = lock.lock(cv)
    assert outer_flags.level == initial_irq
    inner_flags = lock.lock(cv)
    assert inner_flags.level == initial_irq - 1

    lock.unlock(cv, inner_flags)
    assert cv.local_irq == initial_irq - 1
    lock.unlock(cv, outer_flags)
    assert (cv.local_irq, cv.local_tasks, cv.remote_irq, cv.remote_tasks) == (
        initial_irq,
        1,
        1,
        1,
    )


@pytest.mark.parametrize(
    "guard_type, held",
    [
        (GuardBusyWaitPreemption, (0, -1, -1, -1)),
        (GuardBusyWaitIrqSave, (-1, 0, -1, -1)),
        (GuardBusyWaitIrqSavePreemption, (-1, -1, -1, -1)),
    ],
)
def test_combined_busy_wait_guards_nest_and_restore_existing_protection(
    guard_type, held
):
    cv = ContentionVector.zeros()
    initial_stacks = {domain: list(cv.stacks[domain]) for domain in DOMAINS}

    with guard_type(cv, object()):
        outer_stacks = {domain: list(cv.stacks[domain]) for domain in DOMAINS}
        assert tuple(getattr(cv, domain) for domain in DOMAINS) == held
        with (
            pytest.raises(RuntimeError, match="inner action failed"),
            guard_type(cv, object()),
        ):
            assert tuple(getattr(cv, domain) for domain in DOMAINS) == tuple(
                value * 2 for value in held
            )
            raise RuntimeError("inner action failed")
        assert tuple(getattr(cv, domain) for domain in DOMAINS) == held
        assert cv.stacks == outer_stacks

    assert all(getattr(cv, domain) == 0 for domain in DOMAINS)
    assert cv.stacks == initial_stacks


@pytest.mark.parametrize(
    "guard_type, restored_irq",
    [
        (GuardBusyWaitPreemption, -1),
        (GuardBusyWaitIrqSave, 1),
        (GuardBusyWaitIrqSavePreemption, 1),
    ],
)
def test_combined_busy_wait_guards_restore_on_exception_and_keep_body_changes(
    guard_type, restored_irq
):
    cv = ContentionVector.ones()

    with pytest.raises(RuntimeError, match="action failed"), guard_type(cv, object()):
        cv.local_irq -= 2
        cv.local_tasks += 2
        cv.remote_irq += 3
        cv.remote_tasks -= 2
        raise RuntimeError("action failed")

    assert (cv.local_irq, cv.local_tasks, cv.remote_irq, cv.remote_tasks) == (
        restored_irq,
        3,
        4,
        -1,
    )


@pytest.mark.parametrize(
    "guard_type, expected",
    [
        (
            GuardBusyWaitPreemption,
            ["preemption.disable", "lock", "body", "unlock", "preemption.enable"],
        ),
        (
            GuardBusyWaitIrqSave,
            ["irq.save", "lock", "body", "unlock", "irq.restore"],
        ),
        (
            GuardBusyWaitIrqSavePreemption,
            [
                "irq.save",
                "preemption.disable",
                "lock",
                "body",
                "unlock",
                "irq.restore",
                "preemption.enable",
            ],
        ),
    ],
)
def test_combined_busy_wait_guards_protect_acquisition_and_release_in_order(
    monkeypatch, guard_type, expected
):
    events: list[str] = []

    def save_irq(self, cv):
        events.append("irq.save")
        return cv.local_irq

    monkeypatch.setattr(LocalIrq, "save", save_irq)
    monkeypatch.setattr(
        LocalIrq, "restore", lambda self, cv, flags: events.append("irq.restore")
    )
    monkeypatch.setattr(
        Preemption, "disable", lambda self, cv: events.append("preemption.disable")
    )
    monkeypatch.setattr(
        Preemption, "enable", lambda self, cv: events.append("preemption.enable")
    )
    monkeypatch.setattr(BusyWaitLock, "lock", lambda self, cv: events.append("lock"))
    monkeypatch.setattr(
        BusyWaitLock, "unlock", lambda self, cv: events.append("unlock")
    )

    with guard_type(ContentionVector.ones(), object()):
        events.append("body")

    assert events == expected


@pytest.mark.parametrize("local_tasks, remote_tasks", [(1, 1), (0, 0), (2, 4)])
def test_nested_yield_lock_guards_restore_task_contention(local_tasks, remote_tasks):
    cv = ContentionVector(
        local_irq=0, local_tasks=local_tasks, remote_tasks=remote_tasks
    )

    with GuardYieldLock(cv, object()):
        assert (cv.local_tasks, cv.remote_tasks) == (local_tasks - 1, remote_tasks - 1)
        assert (cv.local_irq, cv.remote_irq) == (0, 1)
        with GuardYieldLock(cv, object()):
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

    with pytest.raises(AssertionError, match="action failed"), guard_type(cv, object()):
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

    with GuardYieldTryLock(cv, object()):
        assert all(getattr(cv, domain) == initial - 1 for domain in DOMAINS)
        with GuardYieldTryLock(cv, object()):
            assert all(getattr(cv, domain) == initial - 2 for domain in DOMAINS)
        assert all(getattr(cv, domain) == initial - 1 for domain in DOMAINS)

    assert all(getattr(cv, domain) == initial for domain in DOMAINS)


def test_irq_restore_recovers_saved_target_stack_and_preserves_other_domains():
    cv = ContentionVector.ones()
    target = object()
    irq = LocalIrq()

    with GuardYieldTryLock(cv, target):
        flags = irq.save(cv)
        irq.disable(cv)
        with GuardPreemption(cv):
            irq.restore(cv, flags)
            assert cv.local_irq == 0
            assert cv.stacks["local_irq"] == [target]
            assert cv.stacks["local_tasks"] == [target, None]
            assert cv.stacks["remote_irq"] == [target]
            assert cv.stacks["remote_tasks"] == [target]

    assert all(getattr(cv, domain) == 1 for domain in DOMAINS)
    assert all(not cv.stacks[domain] for domain in DOMAINS)


def test_enabling_competitors_removes_initial_global_protection():
    cv = ContentionVector.zeros()

    LocalMultiTasks().enable(cv)
    RemoteCpus().enable(cv)
    LocalIrq().enable(cv)

    assert all(getattr(cv, domain) == 1 for domain in DOMAINS)
    assert all(not cv.stacks[domain] for domain in DOMAINS)
