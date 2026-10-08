"""Test contention vectors, their partial order and visibility presets."""

from framework.contention import (
    CPUSCOPE_CV,
    EXCLUSIVE_CV,
    FREE_CV,
    FULLSCOPE_CV,
    IRQSCOPE_CV,
    TASKPRIVATE_CV,
    TASKSCOPE_CV,
    TRANSPARENT_CV,
    ContentionVector,
)

DOMAINS = ("local_irq", "local_tasks", "remote_irq", "remote_tasks")


def test_named_constructors_initialize_all_domains():
    ones = ContentionVector.ones()
    zeros = ContentionVector.zeros()

    assert all(getattr(ones, domain) == 1 for domain in DOMAINS)
    assert all(getattr(zeros, domain) == 0 for domain in DOMAINS)


def test_role_defaults_keep_visibility_separate_from_contention_defaults():
    assert all(getattr(FREE_CV, domain) == 1 for domain in DOMAINS)
    assert all(getattr(EXCLUSIVE_CV, domain) == 0 for domain in DOMAINS)
    assert all(getattr(FULLSCOPE_CV, domain) == 1 for domain in DOMAINS)
    assert all(getattr(TRANSPARENT_CV, domain) == 0 for domain in DOMAINS)
    assert all(getattr(TASKPRIVATE_CV, domain) == 0 for domain in DOMAINS)
    assert FREE_CV is not FULLSCOPE_CV
    assert EXCLUSIVE_CV is not TRANSPARENT_CV
    assert TASKPRIVATE_CV is not TRANSPARENT_CV
    assert TASKPRIVATE_CV is not EXCLUSIVE_CV


def test_visibility_scope_vectors_select_their_context_domains():
    assert tuple(getattr(CPUSCOPE_CV, domain) for domain in DOMAINS) == (1, 1, 0, 0)
    assert tuple(getattr(TASKSCOPE_CV, domain) for domain in DOMAINS) == (0, 1, 0, 1)
    assert tuple(getattr(IRQSCOPE_CV, domain) for domain in DOMAINS) == (1, 0, 1, 0)


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
