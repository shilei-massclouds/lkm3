"""Test contention domains and their partial order."""

import pytest

from framework.sync import ContentionVector, GuardLocalIrq

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


@pytest.mark.parametrize("initial_irq", [0, 1])
def test_irq_guard_restores_initial_state_without_reverting_other_domains(initial_irq):
    cv = ContentionVector(local_irq=initial_irq, remote_irq=0)

    with GuardLocalIrq(cv):
        assert cv.local_irq == 0
        assert cv.local_tasks == cv.remote_tasks == 1
        assert cv.remote_irq == 0
        cv.local_tasks = 0

    assert cv.local_irq == initial_irq
    assert cv.local_tasks == cv.remote_irq == 0
    assert cv.remote_tasks == 1


@pytest.mark.parametrize("initial_irq", [0, 1])
def test_irq_guard_restores_state_and_propagates_action_error(initial_irq):
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
            assert cv.local_irq == 0
            raise RuntimeError("inner action failed")
        assert cv.local_irq == 0

    assert cv.local_irq == 1
