"""Test contention domains and their partial order."""

from framework.sync import ContentionVector

DOMAINS = ("local_irq", "local_tasks", "remote_irq", "remote_tasks")


def test_named_constructors_initialize_all_domains_and_remote_limit():
    ones = ContentionVector.ones()
    zeros = ContentionVector.zeros()

    assert all(getattr(ones, domain) == 1 for domain in DOMAINS)
    assert ones._remote_limit == 1
    assert all(getattr(zeros, domain) == 0 for domain in DOMAINS)
    assert zeros._remote_limit == 0


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


def test_remote_limit_is_not_a_competition_domain():
    left = ContentionVector.ones()
    right = ContentionVector.ones()
    left._remote_limit = 0

    assert left <= right
    assert right <= left
    actual = left.min(right)
    assert all(getattr(actual, domain) == 1 for domain in DOMAINS)
    assert left._remote_limit == 0
    assert right._remote_limit == 1
