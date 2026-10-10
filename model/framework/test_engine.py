"""Test Signal Sources and Dispatch"""

from collections import deque
from dataclasses import dataclass, field, fields
from inspect import currentframe, signature
from typing import Any
from warnings import catch_warnings

import pytest

from framework.contention import (
    CPUSCOPE_CV,
    FULLSCOPE_CV,
    TASKPRIVATE_CV,
    TRANSPARENT_CV,
    ContentionVector,
)
from framework.engine import Signal, System, TaskLocalEnv, protected_by, requires_cv
from framework.engine import visibility as declare_visibility
from framework.sync_primitives import (
    GuardBusyWaitIrqSave,
    GuardBusyWaitIrqSavePreemption,
    GuardBusyWaitPreemption,
    GuardLocalIrq,
    GuardYieldLock,
    GuardYieldTryLock,
)
from systems.computer import Computer

DOMAINS = ("local_irq", "local_tasks", "remote_irq", "remote_tasks")


@dataclass
class Receiver(System):
    name: str
    received: list[object] = field(default_factory=list)
    environments: list[ContentionVector] = field(default_factory=list)

    def __repr__(self):
        return self.name

    def _receive(self, sig: Signal):
        self.environments.append(sig.env.cv)
        self.received.append(sig.args["payload"])

    def _enqueue(self, sig: Signal):
        self.environments.append(sig.env.cv)
        sig.chain(self, "_receive", payload=sig.args["payload"])

    def _relay(self, sig: Signal):
        self.environments.append(sig.env.cv)
        self.drive(
            sig.env,
            sig.args["recipient"],
            "_enqueue",
            payload=sig.args["payload"],
        )


@declare_visibility(TRANSPARENT_CV)
class TransparentReceiver(Receiver):
    pass


def test_drive_source_and_nested_events(capsys):
    cv = ContentionVector.ones()
    env = TaskLocalEnv(cv)
    source = Computer()
    relay = TransparentReceiver("Relay")
    target = TransparentReceiver("Target")
    payload = object()

    source.drive(env, relay, "_relay", recipient=target, payload=payload)

    assert len(target.received) == 1
    assert target.received[0] is payload
    assert not relay.received
    assert len(relay.environments) == 1
    assert relay.environments[0] is cv
    assert len(target.environments) == 2
    assert all(env is cv for env in target.environments)
    assert capsys.readouterr().out.splitlines() == [
        "Computer:",
        "    _relay -> Relay",
        "    Relay:",
        "        _enqueue -> Target",
        "        _receive -> Target",
    ]
    assert env.depth == 0


def test_drive_all_source_and_generator(capsys):
    cv = ContentionVector.ones()
    env = TaskLocalEnv(cv)
    source = Computer()
    targets = [
        TransparentReceiver("First"),
        TransparentReceiver("Second"),
    ]
    payload = object()

    source.drive_all(env, (target for target in targets), "_receive", payload=payload)

    for target in targets:
        assert len(target.received) == 1
        assert target.received[0] is payload
        assert len(target.environments) == 1
        assert target.environments[0] is cv
    assert capsys.readouterr().out.splitlines() == [
        "Computer:",
        "    _receive -> First",
        "Computer:",
        "    _receive -> Second",
    ]
    assert env.depth == 0


def test_drive_returns_root_result_without_chained_result():
    env = TaskLocalEnv()
    root_result = object()
    chained_result = object()

    class ReturningTarget(System):
        def _root(self, sig: Signal):
            sig.chain(self, "_chained")
            return root_result

        def _chained(self, sig: Signal):
            return chained_result

    assert System().drive(env, ReturningTarget(), "_root") is root_result


def test_nested_drive_result_is_not_implicitly_returned():
    env = TaskLocalEnv()
    inner_result = object()

    class Nested(System):
        def _outer(self, sig: Signal):
            self.drive(sig.env, self, "_inner")

        def _inner(self, sig: Signal):
            return inner_result

    assert System().drive(env, Nested(), "_outer") is None


def test_drive_all_returns_results_in_target_order():
    env = TaskLocalEnv()
    middle_result = object()

    class ReturningTarget(System):
        def __init__(self, result):
            self.result = result

        def _emit(self, sig: Signal):
            return self.result

    targets = [
        ReturningTarget(None),
        ReturningTarget(middle_result),
        ReturningTarget(None),
    ]

    assert System().drive_all(env, targets, "_emit") == [None, middle_result, None]


def test_drive_all_empty_targets_returns_empty_list():
    assert System().drive_all(TaskLocalEnv(), [], "unused") == []


def test_drive_all_exception_restores_environment_and_stops_iteration():
    parent_queue: deque[Signal] = deque()
    env = TaskLocalEnv(depth=3, signal_queues=[parent_queue])
    calls: list[str] = []

    class Target(System):
        def __init__(self, name, fail=False):
            self.name = name
            self.fail = fail

        def _emit(self, sig: Signal):
            calls.append(self.name)
            if self.fail:
                raise RuntimeError("emit failed")

    targets = [Target("first"), Target("second", fail=True), Target("third")]

    with pytest.raises(RuntimeError, match="emit failed"):
        System().drive_all(env, targets, "_emit")

    assert calls == ["first", "second"]
    assert env.depth == 3
    assert env.signal_queues == [parent_queue]


def test_signal_releases_environment_when_action_asserts():
    cv = ContentionVector.ones()
    env = TaskLocalEnv(cv)
    calls: list[tuple[str, ContentionVector]] = []

    class FailingTarget(System):
        def acquire(self, env: TaskLocalEnv, action: str):
            cv = env.cv
            calls.append(("acquire", cv))
            cv.protect(None, *DOMAINS)
            super().acquire(env, action)

        def _fail(self, sig: Signal):
            calls.append(("action", sig.env.cv))
            assert sig.env.cv.local_irq == 0
            assert False, "action failed"

        def release(self, env: TaskLocalEnv, action: str):
            cv = env.cv
            calls.append(("release", cv))
            cv.unprotect(None, *DOMAINS)

    signal = Signal(FailingTarget(), "_fail", {}, env, deque())

    with pytest.raises(AssertionError, match="action failed"):
        signal.handle()

    assert [phase for phase, _ in calls] == ["acquire", "action", "release"]
    assert all(env is cv for _, env in calls)
    assert cv.local_irq == cv.local_tasks == cv.remote_irq == cv.remote_tasks == 1


def test_system_defaults_require_exclusive_access():
    cv = ContentionVector.ones()
    env = TaskLocalEnv(cv)
    system = System()

    assert not hasattr(system, "visibility")
    visible = system.resolve_visibility()
    assert visible.local_irq == 1
    assert visible.local_tasks == 1
    assert visible.remote_irq == 1
    assert visible.remote_tasks == 1
    assert "visibility" not in signature(System).parameters
    assert "visibility" not in {item.name for item in fields(System)}
    assert not system.check_invariant(env)

    cv.protect(None, *DOMAINS)
    assert system.check_invariant(env)


@pytest.mark.parametrize(
    "cv",
    [
        ContentionVector(local_irq=-1, local_tasks=0, remote_irq=-2, remote_tasks=-3),
        ContentionVector(local_irq=-1, local_tasks=-1, remote_irq=-1, remote_tasks=-1),
    ],
)
def test_redundant_protection_allows_exclusive_dispatch(cv):
    env = TaskLocalEnv(cv)
    target = Receiver("Protected")
    payload = object()

    assert target.check_invariant(env, "_receive")
    assert target.violated_domains(env, "_receive") == []
    Computer().drive(env, target, "_receive", payload=payload)

    assert target.received == [payload]


@pytest.mark.parametrize(
    "domain", ["local_irq", "local_tasks", "remote_irq", "remote_tasks"]
)
def test_negative_contention_cannot_offset_a_positive_domain(domain):
    cv = ContentionVector(local_irq=-1, local_tasks=-1, remote_irq=-1, remote_tasks=-1)
    env = TaskLocalEnv(cv)
    setattr(cv, domain, 1)
    target = Receiver("Target")

    assert not target.check_invariant(env, "_receive")
    assert target.violated_domains(env, "_receive") == [domain]
    with pytest.raises(AssertionError, match=f"violated domains: {domain}"):
        Computer().drive(env, target, "_receive", payload=object())

    assert not target.received


def test_invariant_masks_visibility_against_exclusive_boundary():
    cv = ContentionVector.ones()
    env = TaskLocalEnv(cv)
    visibility = ContentionVector.zeros()
    visibility.remote_tasks = 1

    @declare_visibility(visibility)
    class VisibleSystem(System):
        pass

    system = VisibleSystem()

    assert not system.check_invariant(env)

    assert system.resolve_visibility().remote_tasks == 1
    assert system.check_invariant(TaskLocalEnv(ContentionVector(remote_tasks=0)))

    @declare_visibility(TRANSPARENT_CV)
    class FullyHidden(System):
        pass

    assert FullyHidden().check_invariant(env)
    assert cv.local_irq == cv.local_tasks == cv.remote_irq == cv.remote_tasks == 1


def test_visibility_defaults_to_full_scope_and_resolves_method_before_class():
    @declare_visibility(ContentionVector(remote_tasks=0))
    class VisibleReceiver(Receiver):
        @declare_visibility(ContentionVector(local_irq=0))
        def _receive(self, sig: Signal):
            super()._receive(sig)

    target = VisibleReceiver("Visible")
    method_visibility = target.resolve_visibility("_receive")
    class_visibility = target.resolve_visibility("_enqueue")

    assert method_visibility.local_irq == 0
    assert method_visibility.local_tasks == 1
    assert method_visibility.remote_irq == 1
    assert method_visibility.remote_tasks == 1
    assert class_visibility.remote_tasks == 0
    method_visibility.local_irq = 1
    assert target.resolve_visibility("_receive").local_irq == 0
    default_visibility = System().resolve_visibility()
    assert default_visibility is not FULLSCOPE_CV
    assert all(getattr(default_visibility, domain) == 1 for domain in DOMAINS)

    @declare_visibility(TRANSPARENT_CV)
    class HiddenReceiver(Receiver):
        pass

    assert all(
        getattr(HiddenReceiver("Hidden").resolve_visibility(), domain) == 0
        for domain in DOMAINS
    )

    assert target.check_invariant(
        TaskLocalEnv(ContentionVector(zero=True, local_irq=0)), "_receive"
    )
    assert target.check_invariant(
        TaskLocalEnv(ContentionVector(zero=True, remote_tasks=0)), "_enqueue"
    )
    assert not target.check_invariant(TaskLocalEnv(ContentionVector.ones()), "_receive")


def test_action_name_selects_transparent_default_visibility():
    class NamedReceiver(System):
        def _closed(self, sig: Signal):
            pass

        def open(self, sig: Signal):
            pass

    target = NamedReceiver()
    closed = target.resolve_visibility("_closed")
    opened = target.resolve_visibility("open")

    assert all(
        getattr(closed, domain) == getattr(FULLSCOPE_CV, domain) for domain in DOMAINS
    )
    assert all(
        getattr(opened, domain) == getattr(TRANSPARENT_CV, domain) for domain in DOMAINS
    )
    assert not target.check_invariant(TaskLocalEnv(ContentionVector.ones()), "_closed")
    assert target.check_invariant(TaskLocalEnv(ContentionVector.ones()), "open")


def test_task_private_visibility_adds_context_manager_protocol():
    @declare_visibility(TASKPRIVATE_CV)
    class TaskPrivateSystem(System):
        pass

    target: Any = TaskPrivateSystem()

    with target as scoped:
        assert scoped is target


def test_transparent_visibility_masks_a_convenience_wrapper():
    @declare_visibility(TRANSPARENT_CV)
    class ConvenienceWrapper(System):
        def _run(self, sig: Signal):
            pass

    target = ConvenienceWrapper()
    assert all(
        getattr(target.resolve_visibility("_run"), domain) == 0 for domain in DOMAINS
    )
    assert target.check_invariant(TaskLocalEnv(ContentionVector.ones()), "_run")


def test_protected_by_requires_enclosing_lock_without_changing_visibility():
    class ConsoleLock(System):
        pass

    @protected_by(ConsoleLock)
    @declare_visibility(TRANSPARENT_CV)
    class ProtectedHelper(Receiver):
        pass

    target = ProtectedHelper("Protected")
    cv = ContentionVector.ones()
    env = TaskLocalEnv(cv)

    assert all(
        getattr(target.resolve_visibility("_receive"), domain)
        == getattr(TRANSPARENT_CV, domain)
        for domain in DOMAINS
    )
    assert target.resolve_protected_by("_receive") == (ConsoleLock,)
    assert target.violated_domains(env, "_receive") == list(DOMAINS)

    with GuardYieldTryLock(cv, ConsoleLock):
        Computer().drive(env, target, "_receive", payload="accepted")

    assert target.received == ["accepted"]


def test_method_protected_by_overrides_class_declaration():
    class OuterLock(System):
        pass

    class InnerLock(System):
        pass

    @protected_by(OuterLock)
    class ProtectedReceiver(Receiver):
        @protected_by(InnerLock)
        def _receive(self, sig: Signal):
            super()._receive(sig)

    target = ProtectedReceiver("Protected")
    assert target.resolve_protected_by("_receive") == (InnerLock,)
    assert target.resolve_protected_by("_enqueue") == (OuterLock,)


def test_drive_stops_before_action_when_invariant_fails():
    cv = ContentionVector.ones()
    env = TaskLocalEnv(cv)
    source = Computer()
    target = Receiver("Target")

    with pytest.raises(AssertionError, match="Contention invariant violated"):
        source.drive(env, target, "_receive", payload=object())

    assert not target.received
    assert not target.environments
    assert env.depth == 0


def test_yield_try_lock_allows_exclusive_dispatch_when_irq_contention_remains():
    cv = ContentionVector.ones()
    env = TaskLocalEnv(cv)
    target = Receiver("Target")
    payload = object()
    source = Computer()

    with GuardYieldLock(cv, target):
        with pytest.raises(
            AssertionError, match="violated domains: local_irq, remote_irq"
        ):
            source.drive(env, target, "_receive", payload=payload)
        assert not target.received
        with GuardYieldTryLock(cv, target):
            source.drive(env, target, "_receive", payload=payload)
        assert (cv.local_irq, cv.remote_irq) == (1, 1)
        assert (cv.local_tasks, cv.remote_tasks) == (0, 0)

    assert target.received == [payload]
    assert target.environments[0] is cv
    assert cv.local_irq == cv.local_tasks == cv.remote_irq == cv.remote_tasks == 1


@pytest.mark.parametrize(
    "guard_type, unprotected_domain",
    [
        (GuardBusyWaitPreemption, "local_irq"),
        (GuardBusyWaitIrqSave, "local_tasks"),
        (GuardBusyWaitIrqSavePreemption, None),
    ],
)
def test_combined_busy_wait_guards_enforce_exclusive_dispatch_boundaries(
    guard_type, unprotected_domain
):
    cv = ContentionVector.ones()
    env = TaskLocalEnv(cv)
    source = Computer()
    target = Receiver("Target")
    payload = object()

    with guard_type(cv, target):
        if unprotected_domain is None:
            source.drive(env, target, "_receive", payload=payload)
            assert target.received == [payload]
        else:
            with pytest.raises(
                AssertionError, match=f"violated domains: {unprotected_domain}"
            ):
                source.drive(env, target, "_receive", payload=payload)
            assert not target.received

    assert all(getattr(cv, domain) == 1 for domain in DOMAINS)
    assert env.depth == 0 and env.signal_queues == []


def test_lock_targets_are_checked_by_identity_before_the_action_runs():
    cv = ContentionVector.ones()
    env = TaskLocalEnv(cv)
    target, equal_target = Receiver("Target"), Receiver("Target")
    assert target == equal_target and target is not equal_target

    with GuardYieldTryLock(cv, equal_target):
        assert all(getattr(cv, domain) == 0 for domain in DOMAINS)
        assert target.violated_domains(env, "_receive") == list(DOMAINS)
        with pytest.raises(AssertionError, match="Contention invariant violated"):
            Computer().drive(env, target, "_receive", payload="rejected")

        assert not target.received and not target.environments


def test_each_domain_requires_its_own_target_or_global_protection():
    cv = ContentionVector.ones()
    env = TaskLocalEnv(cv)
    target, other = Receiver("Target"), Receiver("Other")

    with GuardBusyWaitIrqSavePreemption(cv, other):
        assert target.violated_domains(env, "_receive") == [
            "remote_irq",
            "remote_tasks",
        ]
        with GuardBusyWaitPreemption(cv, target):
            Computer().drive(env, target, "_receive", payload="accepted")
            # The outer target remains protected even with a different stack top.
            assert other.check_invariant(env, "_receive")
        assert target.violated_domains(env, "_receive") == [
            "remote_irq",
            "remote_tasks",
        ]

    assert target.received == ["accepted"]
    assert all(not cv.stacks[domain] for domain in DOMAINS)


def test_global_protection_anywhere_in_a_stack_covers_other_targets():
    cv = ContentionVector.ones()
    env = TaskLocalEnv(cv)
    target, other = Receiver("Target"), Receiver("Other")

    with GuardYieldTryLock(cv, None), GuardYieldTryLock(cv, other):
        assert all(cv.stacks[domain] == [None, other] for domain in DOMAINS)
        Computer().drive(env, target, "_receive", payload="accepted")

    assert target.received == ["accepted"]


def test_numerical_zero_without_a_protection_reference_is_rejected():
    cv = ContentionVector.ones()
    env = TaskLocalEnv(cv)
    target = Receiver("Target")
    for domain in DOMAINS:
        setattr(cv, domain, 0)

    assert target.violated_domains(env, "_receive") == list(DOMAINS)
    assert not target.check_invariant(env, "_receive")
    assert TransparentReceiver("Wrapper").check_invariant(env, "_receive")


def test_matching_stack_cannot_override_positive_contention():
    cv = ContentionVector.ones()
    env = TaskLocalEnv(cv)
    target = Receiver("Target")

    with GuardYieldTryLock(cv, target):
        cv.remote_tasks = 1
        assert target.violated_domains(env, "_receive") == ["remote_tasks"]
        assert not target.check_invariant(env, "_receive")


@pytest.mark.parametrize("scope", [CPUSCOPE_CV, TRANSPARENT_CV])
def test_hidden_domains_do_not_require_matching_lock_targets(scope):
    @declare_visibility(scope)
    class ScopedReceiver(Receiver):
        pass

    cv = ContentionVector.ones()
    env = TaskLocalEnv(cv)
    target = ScopedReceiver("Target")

    with GuardBusyWaitIrqSavePreemption(cv, object()):
        Computer().drive(env, target, "_receive", payload="accepted")

    assert target.received == ["accepted"]


def test_targeted_yield_lock_keeps_local_protection_target_specific():
    cv = ContentionVector.ones()
    env = TaskLocalEnv(cv)
    target, other = Receiver("Target"), Receiver("Other")

    with GuardYieldTryLock(cv, other), GuardBusyWaitPreemption(cv, target):
        assert target.violated_domains(env, "_receive") == ["local_irq"]
        with GuardLocalIrq(cv):
            Computer().drive(env, target, "_receive", payload="accepted")

    assert target.received == ["accepted"]


@pytest.mark.parametrize("declaration", ["class", "method"])
def test_requires_cv_warns_at_creation_and_preserves_dispatch(declaration):
    class LegacyReceiver(Receiver):
        def _receive(self, sig: Signal):
            super()._receive(sig)

    frame = currentframe()
    assert frame is not None
    with catch_warnings(record=True, action="always") as caught:
        declaration_line = frame.f_lineno + 1
        decorate = requires_cv(ContentionVector(remote_irq=0))

        if declaration == "class":
            assert decorate(LegacyReceiver) is LegacyReceiver
        else:
            method = LegacyReceiver._receive
            assert decorate(method) is method

        target = LegacyReceiver("Legacy")
        cv = ContentionVector(remote_irq=0)
        Computer().drive(TaskLocalEnv(cv), target, "_receive", payload="allowed")
        with pytest.raises(AssertionError, match="violated domains: remote_irq"):
            Computer().drive(
                TaskLocalEnv(ContentionVector.ones()),
                target,
                "_receive",
                payload="blocked",
            )

    assert len(caught) == 1
    warning = caught[0]
    assert warning.category is DeprecationWarning
    assert str(warning.message) == (
        "requires_cv is deprecated; use SyncPrimitive and visibility instead."
    )
    assert warning.filename == __file__
    assert warning.lineno == declaration_line
    assert target.received == ["allowed"]
    assert target.environments == [cv]


def test_nested_drives_finish_before_their_callers_pending_signals():
    events: list[str] = []
    env = TaskLocalEnv()

    class Nested(System):
        def _outer(self, sig: Signal):
            events.append("outer start")
            sig.chain(self, "_record", event="outer next")
            self.drive(sig.env, self, "_inner", outer=sig)
            events.append("outer resumed")

        def _inner(self, sig: Signal):
            events.append("inner start")
            outer = sig.args["outer"]
            assert sig.queue is not outer.queue
            assert sig.env.signal_queues == [outer.queue, sig.queue]
            # Chaining from an outer signal still belongs to the outer invocation.
            outer.chain(self, "_record", event="outer late")
            sig.chain(self, "_record", event="inner next")

        def _record(self, sig: Signal):
            events.append(sig.args["event"])

    target = Nested()
    System().drive(env, target, "_outer")

    assert events == [
        "outer start",
        "inner start",
        "inner next",
        "outer resumed",
        "outer next",
        "outer late",
    ]
    assert env.depth == 0 and env.signal_queues == []


@pytest.mark.parametrize("caught", [False, True])
def test_nested_failure_restores_surrounding_queue_stack_and_depth(caught):
    parent_queue: deque[Signal] = deque()
    env = TaskLocalEnv(depth=3, signal_queues=[parent_queue])
    events: list[str] = []

    class Nested(System):
        def _outer(self, sig: Signal):
            sig.chain(self, "_record", event="outer next")
            queue = sig.queue
            try:
                self.drive(sig.env, self, "_inner")
            except AssertionError:
                assert sig.env.depth == 4
                assert sig.env.signal_queues == [parent_queue, queue]
                if not caught:
                    raise
                events.append("caught")

        def _inner(self, sig: Signal):
            sig.chain(self, "_record", event="abandoned")
            assert False, "inner failed"

        def _record(self, sig: Signal):
            events.append(sig.args["event"])

    target = Nested()
    if caught:
        System().drive(env, target, "_outer")
        assert events == ["caught", "outer next"]
    else:
        with pytest.raises(AssertionError, match="inner failed"):
            System().drive(env, target, "_outer")
        assert events == []
    assert env.depth == 3
    assert env.signal_queues == [parent_queue]
