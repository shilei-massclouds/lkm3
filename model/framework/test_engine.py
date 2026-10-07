"""Test Signal Sources and Dispatch"""

from collections import deque
from dataclasses import dataclass, field, fields
from inspect import currentframe, signature
from warnings import catch_warnings

import pytest

from framework.engine import Signal, System, TaskLocalEnv, requires_cv
from framework.engine import visibility as declare_visibility
from framework.sync import (
    FULLSCOPE_CV,
    TRANSPARENT_CV,
    ContentionVector,
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

    def receive(self, sig: Signal):
        self.environments.append(sig.env.cv)
        self.received.append(sig.args["payload"])

    def enqueue(self, sig: Signal):
        self.environments.append(sig.env.cv)
        sig.chain(self, "receive", payload=sig.args["payload"])

    def relay(self, sig: Signal):
        self.environments.append(sig.env.cv)
        self.drive(
            sig.env,
            sig.args["recipient"],
            "enqueue",
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

    source.drive(env, relay, "relay", recipient=target, payload=payload)

    assert len(target.received) == 1
    assert target.received[0] is payload
    assert not relay.received
    assert len(relay.environments) == 1
    assert relay.environments[0] is cv
    assert len(target.environments) == 2
    assert all(env is cv for env in target.environments)
    assert capsys.readouterr().out.splitlines() == [
        "Computer:",
        "    relay -> Relay",
        "    Relay:",
        "        enqueue -> Target",
        "        receive -> Target",
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

    source.drive_all(env, (target for target in targets), "receive", payload=payload)

    for target in targets:
        assert len(target.received) == 1
        assert target.received[0] is payload
        assert len(target.environments) == 1
        assert target.environments[0] is cv
    assert capsys.readouterr().out.splitlines() == [
        "Computer:",
        "    receive -> First",
        "Computer:",
        "    receive -> Second",
    ]
    assert env.depth == 0


def test_signal_releases_environment_when_action_asserts():
    cv = ContentionVector.ones()
    env = TaskLocalEnv(cv)
    calls: list[tuple[str, ContentionVector]] = []

    class FailingTarget(System):
        def acquire(self, env: TaskLocalEnv, action: str):
            cv = env.cv
            calls.append(("acquire", cv))
            cv.local_irq = 0
            cv.local_tasks = 0
            cv.remote_irq = 0
            cv.remote_tasks = 0
            super().acquire(env, action)

        def fail(self, sig: Signal):
            calls.append(("action", sig.env.cv))
            assert sig.env.cv.local_irq == 0
            assert False, "action failed"

        def release(self, env: TaskLocalEnv, action: str):
            cv = env.cv
            calls.append(("release", cv))
            cv.local_irq = 1
            cv.local_tasks = 1
            cv.remote_irq = 1
            cv.remote_tasks = 1

    signal = Signal(FailingTarget(), "fail", {}, env, deque())

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

    cv.local_irq = 0
    cv.local_tasks = 0
    cv.remote_irq = 0
    cv.remote_tasks = 0
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

    assert target.check_invariant(env, "receive")
    assert target.violated_domains(env, "receive") == []
    Computer().drive(env, target, "receive", payload=payload)

    assert target.received == [payload]


@pytest.mark.parametrize(
    "domain", ["local_irq", "local_tasks", "remote_irq", "remote_tasks"]
)
def test_negative_contention_cannot_offset_a_positive_domain(domain):
    cv = ContentionVector(local_irq=-1, local_tasks=-1, remote_irq=-1, remote_tasks=-1)
    env = TaskLocalEnv(cv)
    setattr(cv, domain, 1)
    target = Receiver("Target")

    assert not target.check_invariant(env, "receive")
    assert target.violated_domains(env, "receive") == [domain]
    with pytest.raises(AssertionError, match=f"violated domains: {domain}"):
        Computer().drive(env, target, "receive", payload=object())

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
        def receive(self, sig: Signal):
            super().receive(sig)

    target = VisibleReceiver("Visible")
    method_visibility = target.resolve_visibility("receive")
    class_visibility = target.resolve_visibility("enqueue")

    assert method_visibility.local_irq == 0
    assert method_visibility.local_tasks == 1
    assert method_visibility.remote_irq == 1
    assert method_visibility.remote_tasks == 1
    assert class_visibility.remote_tasks == 0
    method_visibility.local_irq = 1
    assert target.resolve_visibility("receive").local_irq == 0
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
        TaskLocalEnv(ContentionVector(zero=True, local_irq=0)), "receive"
    )
    assert target.check_invariant(
        TaskLocalEnv(ContentionVector(zero=True, remote_tasks=0)), "enqueue"
    )
    assert not target.check_invariant(TaskLocalEnv(ContentionVector.ones()), "receive")


def test_transparent_visibility_masks_a_convenience_wrapper():
    @declare_visibility(TRANSPARENT_CV)
    class ConvenienceWrapper(System):
        def run(self, sig: Signal):
            pass

    target = ConvenienceWrapper()
    assert all(
        getattr(target.resolve_visibility("run"), domain) == 0 for domain in DOMAINS
    )
    assert target.check_invariant(TaskLocalEnv(ContentionVector.ones()), "run")


def test_drive_stops_before_action_when_invariant_fails():
    cv = ContentionVector.ones()
    env = TaskLocalEnv(cv)
    source = Computer()
    target = Receiver("Target")

    with pytest.raises(AssertionError, match="Contention invariant violated"):
        source.drive(env, target, "receive", payload=object())

    assert not target.received
    assert not target.environments
    assert env.depth == 0


def test_yield_try_lock_allows_exclusive_dispatch_when_irq_contention_remains():
    cv = ContentionVector.ones()
    env = TaskLocalEnv(cv)
    target = Receiver("Target")
    payload = object()
    source = Computer()

    with GuardYieldLock(cv):
        with pytest.raises(
            AssertionError, match="violated domains: local_irq, remote_irq"
        ):
            source.drive(env, target, "receive", payload=payload)
        assert not target.received
        with GuardYieldTryLock(cv):
            source.drive(env, target, "receive", payload=payload)
        assert (cv.local_irq, cv.remote_irq) == (1, 1)
        assert (cv.local_tasks, cv.remote_tasks) == (0, 0)

    assert target.received == [payload]
    assert target.environments[0] is cv
    assert cv.local_irq == cv.local_tasks == cv.remote_irq == cv.remote_tasks == 1


@pytest.mark.parametrize("declaration", ["class", "method"])
def test_requires_cv_warns_at_creation_and_preserves_dispatch(declaration):
    class LegacyReceiver(Receiver):
        def receive(self, sig: Signal):
            super().receive(sig)

    frame = currentframe()
    assert frame is not None
    with catch_warnings(record=True, action="always") as caught:
        declaration_line = frame.f_lineno + 1
        decorate = requires_cv(ContentionVector(remote_irq=0))

        if declaration == "class":
            assert decorate(LegacyReceiver) is LegacyReceiver
        else:
            method = LegacyReceiver.receive
            assert decorate(method) is method

        target = LegacyReceiver("Legacy")
        cv = ContentionVector(remote_irq=0)
        Computer().drive(TaskLocalEnv(cv), target, "receive", payload="allowed")
        with pytest.raises(AssertionError, match="violated domains: remote_irq"):
            Computer().drive(
                TaskLocalEnv(ContentionVector.ones()),
                target,
                "receive",
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
        def outer(self, sig: Signal):
            events.append("outer start")
            sig.chain(self, "record", event="outer next")
            self.drive(sig.env, self, "inner", outer=sig)
            events.append("outer resumed")

        def inner(self, sig: Signal):
            events.append("inner start")
            outer = sig.args["outer"]
            assert sig.queue is not outer.queue
            assert sig.env.signal_queues == [outer.queue, sig.queue]
            # Chaining from an outer signal still belongs to the outer invocation.
            outer.chain(self, "record", event="outer late")
            sig.chain(self, "record", event="inner next")

        def record(self, sig: Signal):
            events.append(sig.args["event"])

    target = Nested()
    System().drive(env, target, "outer")

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
        def outer(self, sig: Signal):
            sig.chain(self, "record", event="outer next")
            queue = sig.queue
            try:
                self.drive(sig.env, self, "inner")
            except AssertionError:
                assert sig.env.depth == 4
                assert sig.env.signal_queues == [parent_queue, queue]
                if not caught:
                    raise
                events.append("caught")

        def inner(self, sig: Signal):
            sig.chain(self, "record", event="abandoned")
            assert False, "inner failed"

        def record(self, sig: Signal):
            events.append(sig.args["event"])

    target = Nested()
    if caught:
        System().drive(env, target, "outer")
        assert events == ["caught", "outer next"]
    else:
        with pytest.raises(AssertionError, match="inner failed"):
            System().drive(env, target, "outer")
        assert events == []
    assert env.depth == 3
    assert env.signal_queues == [parent_queue]
