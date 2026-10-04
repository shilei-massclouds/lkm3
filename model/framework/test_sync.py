"""Test contention domains and their partial order."""

import pytest

from framework.sync import (
    ContentionVector,
    GuardLocalIrq,
    GuardYieldLock,
    GuardYieldTryLock,
)

DOMAINS = ("local_irq", "local_tasks", "remote_irq", "remote_tasks")


def test_named_constructors_initialize_all_domains():
    ones = ContentionVector.ones()
    zeros = ContentionVector.zeros()

    assert all(getattr(ones, domain) == 1 for domain in DOMAINS)
    assert all(getattr(zeros, domain) == 0 for domain in DOMAINS)


def test_minimum_combines_domains_without_changing_inputs():
    left = ContentionVector.ones()
    left.local_tasks = 0
    left.remote_tasks = 0
    right = ContentionVector.ones()
    right.local_irq = 0
    right.remote_tasks = 0

    actual = left.min(right)

    assert all(
        getattr(actual, domain) == expected
        for domain, expected in zip(DOMAINS, (0, 0, 1, 0))
    )
    assert all(
        getattr(left, domain) == expected
        for domain, expected in zip(DOMAINS, (1, 0, 1, 0))
    )
    assert all(
        getattr(right, domain) == expected
        for domain, expected in zip(DOMAINS, (0, 1, 1, 0))
    )
    assert actual is not left and actual is not right
    assert actual <= left and actual <= right


def test_comparison_requires_every_domain_to_satisfy_the_limit():
    left = ContentionVector.ones()
    left.local_tasks = 0
    right = ContentionVector.ones()
    right.local_irq = 0
    equal = ContentionVector.ones()
    equal.local_tasks = 0

    assert left <= equal
    assert equal <= left
    assert not left <= right
    assert not right <= left
    assert left <= ContentionVector.ones()
    assert ContentionVector.zeros() <= left


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


def test_irq_guard_restores_state_and_propagates_action_error():
    initial_irq = 1
    cv = ContentionVector(local_irq=initial_irq)
    error = RuntimeError("action failed")

    with pytest.raises(RuntimeError) as exc_info, GuardLocalIrq(cv):
        assert cv.local_irq == 0
        raise error

    assert exc_info.value is error
    assert cv.local_irq == initial_irq


def test_nested_irq_guards_restore_the_surrounding_irq_state():
    cv = ContentionVector.ones()

    with GuardLocalIrq(cv):
        with (
            pytest.raises(RuntimeError, match="inner action failed"),
            GuardLocalIrq(cv),
        ):
            assert cv.local_irq == -1
            raise RuntimeError("inner action failed")
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
def test_yield_guard_restores_on_error_without_reverting_body_changes(guard_type):
    cv = ContentionVector.ones()
    error = RuntimeError("action failed")

    with pytest.raises(RuntimeError) as exc_info, guard_type(cv):
        cv.remote_tasks += 2
        cv.local_irq -= 1
        raise error

    assert exc_info.value is error
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
