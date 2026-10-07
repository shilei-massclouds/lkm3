"""Test Signal Sources and Dispatch"""

from collections import deque
from dataclasses import dataclass, field, fields
from inspect import signature

import pytest

from framework.engine import Signal, System, TaskLocalEnv, requires_cv
from framework.engine import visibility as declare_visibility
from framework.sync import (
    EXCLUSIVE_CV,
    FREE_CV,
    ContentionVector,
    GuardYieldLock,
    GuardYieldTryLock,
)
from kernel.params import CmdItem
from systems.computer import Computer


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


@requires_cv(FREE_CV)
class SharedReceiver(Receiver):
    pass


def test_drive_source_and_nested_events(capsys):
    cv = ContentionVector.ones()
    env = TaskLocalEnv(cv)
    source = Computer()
    relay = SharedReceiver("Relay")
    target = SharedReceiver("Target")
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
        SharedReceiver("First"),
        SharedReceiver("Second"),
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
    requirement = system.resolve_requires_cv()
    assert requirement.local_irq == 0
    assert requirement.local_tasks == 0
    assert requirement.remote_irq == 0
    assert requirement.remote_tasks == 0
    requirement.local_irq = 1
    assert system.resolve_requires_cv().local_irq == EXCLUSIVE_CV.local_irq == 0
    assert not hasattr(system, "requires_cv")
    assert "visibility" not in signature(System).parameters
    assert "visibility" not in {item.name for item in fields(System)}
    assert "requires_cv" not in signature(System).parameters
    assert "requires_cv" not in {item.name for item in fields(System)}
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


def test_invariant_masks_visibility_and_checks_each_required_domain():
    cv = ContentionVector.ones()
    env = TaskLocalEnv(cv)
    visibility = ContentionVector.zeros()
    visibility.remote_tasks = 1

    @declare_visibility(visibility)
    class VisibleSystem(System):
        pass

    system = VisibleSystem()

    assert not system.check_invariant(env)

    @requires_cv(ContentionVector(zero=True, remote_tasks=1))
    class TaskTolerant(System):
        pass

    assert not TaskTolerant().check_invariant(TaskLocalEnv(ContentionVector.ones()))

    @declare_visibility(visibility)
    class VisibleTaskTolerant(TaskTolerant):
        pass

    tolerant = VisibleTaskTolerant()
    assert tolerant.resolve_visibility().remote_tasks == 1
    assert tolerant.check_invariant(env)

    @declare_visibility(ContentionVector.zeros())
    class FullyHidden(System):
        pass

    assert FullyHidden().check_invariant(env)
    assert cv.local_irq == cv.local_tasks == cv.remote_irq == cv.remote_tasks == 1


def test_visibility_defaults_to_free_and_resolves_method_before_class():
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
    assert all(
        getattr(System().resolve_visibility(), domain) == 1
        for domain in ("local_irq", "local_tasks", "remote_irq", "remote_tasks")
    )

    @declare_visibility(ContentionVector.zeros())
    class HiddenReceiver(Receiver):
        pass

    assert all(
        getattr(HiddenReceiver("Hidden").resolve_visibility(), domain) == 0
        for domain in ("local_irq", "local_tasks", "remote_irq", "remote_tasks")
    )

    assert target.check_invariant(
        TaskLocalEnv(ContentionVector(zero=True, local_irq=0)), "receive"
    )
    assert target.check_invariant(
        TaskLocalEnv(ContentionVector(zero=True, remote_tasks=0)), "enqueue"
    )
    assert not target.check_invariant(TaskLocalEnv(ContentionVector.ones()), "receive")


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


def test_requires_cv_class_declaration_controls_signal_dispatch():
    @requires_cv(ContentionVector(remote_irq=0))
    @dataclass
    class SharedReceiver(Receiver):
        pass

    target = SharedReceiver("Shared")
    cv = ContentionVector(remote_irq=0)
    env = TaskLocalEnv(cv)
    payload = object()

    Computer().drive(env, target, "receive", payload=payload)

    assert target.received == [payload]
    assert target.environments == [cv]
    with pytest.raises(AssertionError, match="requires_cv="):
        Computer().drive(
            TaskLocalEnv(ContentionVector.ones()), target, "receive", payload=object()
        )
    assert target.received == [payload]


@pytest.mark.parametrize("declaration", ["class", "method"])
def test_requires_cv_copies_declarations_and_resolved_requirements(declaration):
    default = ContentionVector(zero=True, local_irq=1, remote_tasks=1)

    if declaration == "class":

        @requires_cv(default)
        class ClassReceiver(Receiver):
            pass

        receiver_type = ClassReceiver
    else:

        class MethodReceiver(Receiver):
            @requires_cv(default)
            def receive(self, sig: Signal):
                super().receive(sig)

        receiver_type = MethodReceiver

    default.local_irq = 0
    first = receiver_type("First")
    second = receiver_type("Second")
    resolved = first.resolve_requires_cv("receive")
    resolved.remote_tasks = 0
    other = second.resolve_requires_cv("receive")

    assert resolved is not other
    assert other is not default
    assert other.local_irq == 1
    assert other.local_tasks == 0
    assert other.remote_irq == 0
    assert other.remote_tasks == 1
    assert first.resolve_requires_cv("receive").remote_tasks == 1
    assert System().resolve_requires_cv().local_irq == 0
    assert Receiver("Exclusive").resolve_requires_cv("receive").remote_tasks == 0

    cv = ContentionVector(zero=True, local_irq=1, remote_tasks=1)
    env = TaskLocalEnv(cv)
    Computer().drive(env, first, "receive", payload="copied requirement")
    assert first.received == ["copied requirement"]


def test_requires_cv_is_inherited_and_can_be_overridden_by_subclasses():
    @requires_cv(ContentionVector.ones())
    @dataclass
    class SharedSystem(System):
        name: str

    class PlainChild(SharedSystem):
        pass

    @dataclass
    class DataclassChild(SharedSystem):
        count: int

    @requires_cv(ContentionVector.zeros())
    @dataclass
    class ExclusiveChild(SharedSystem):
        pass

    cv = ContentionVector.ones()
    env = TaskLocalEnv(cv)
    plain = PlainChild("plain")
    child = DataclassChild("child", 3)

    assert plain.check_invariant(env)
    assert child.name == "child" and child.count == 3
    assert child.check_invariant(env)
    assert not ExclusiveChild("exclusive").check_invariant(env)
    assert SharedSystem("parent").check_invariant(env)
    assert plain.resolve_requires_cv().local_irq == 1
    assert DataclassChild("another", 1).resolve_requires_cv().local_irq == 1


def test_class_declarations_follow_mro_without_inherited_attribute_shortcuts():
    @requires_cv(EXCLUSIVE_CV)
    class Root(System):
        pass

    class Left(Root):
        pass

    @requires_cv(FREE_CV)
    class Right(Root):
        pass

    class Diamond(Left, Right):
        pass

    class ReverseDiamond(Right, Left):
        pass

    @requires_cv(EXCLUSIVE_CV)
    class RestrictedLeft(Left):
        pass

    class LeftPriority(RestrictedLeft, Right):
        pass

    class RightPriority(Right, RestrictedLeft):
        pass

    @requires_cv(ContentionVector(local_irq=0))
    class RestrictedDiamond(Diamond):
        pass

    cv = ContentionVector.ones()
    env = TaskLocalEnv(cv)
    assert not Left().check_invariant(env)
    assert Diamond().check_invariant(env)
    assert ReverseDiamond().check_invariant(env)
    assert not LeftPriority().check_invariant(env)
    assert RightPriority().check_invariant(env)
    assert not RestrictedDiamond().check_invariant(env)
    assert RestrictedDiamond().check_invariant(
        TaskLocalEnv(ContentionVector(local_irq=0))
    )


def test_requires_cv_supports_custom_initializers():
    @requires_cv(ContentionVector.ones())
    class SharedItem(CmdItem):
        pass

    item = SharedItem("earlycon", "sbi")

    assert SharedItem.__init__ is CmdItem.__init__
    assert signature(SharedItem) == signature(CmdItem)
    assert item.key == "earlycon" and item.val == "sbi"
    assert item.check_invariant(TaskLocalEnv(ContentionVector.ones()))
    assert not CmdItem("earlycon", "sbi").check_invariant(
        TaskLocalEnv(ContentionVector.ones())
    )


def test_class_decorator_preserves_custom_constructor_and_dataclass_metadata():
    class ConfiguredSystem(System):
        def __init__(self, name: str, /, **options: object):
            super().__init__()
            self.name = name
            self.options = options

    original_init = ConfiguredSystem.__init__
    original_signature = signature(ConfiguredSystem)
    original_fields = ConfiguredSystem.__dataclass_fields__

    assert requires_cv(FREE_CV)(ConfiguredSystem) is ConfiguredSystem
    assert ConfiguredSystem.__init__ is original_init
    assert signature(ConfiguredSystem) == original_signature
    assert ConfiguredSystem.__dataclass_fields__ is original_fields

    target = ConfiguredSystem("configured", setting=3)
    assert target.name == "configured"
    assert target.options == {"setting": 3}
    assert not hasattr(target, "visibility")
    assert not hasattr(target, "requires_cv")
    assert target.check_invariant(TaskLocalEnv(ContentionVector.ones()))


def test_class_declaration_also_works_below_dataclass():
    @dataclass
    @requires_cv(FREE_CV)
    class SharedSystem(System):
        name: str

    target = SharedSystem("shared")
    assert target.name == "shared"
    assert target.check_invariant(TaskLocalEnv(ContentionVector.ones()))
    assert "requires_cv" not in signature(SharedSystem).parameters


@pytest.mark.parametrize(
    "class_requirement, method_requirement, allowed",
    [(FREE_CV, EXCLUSIVE_CV, False), (EXCLUSIVE_CV, FREE_CV, True)],
)
def test_method_declarations_can_tighten_or_relax_class_requirements(
    class_requirement, method_requirement, allowed
):
    @requires_cv(class_requirement)
    class MethodReceiver(Receiver):
        @requires_cv(method_requirement)
        def receive(self, sig: Signal):
            super().receive(sig)

    target = MethodReceiver("Method")
    cv = ContentionVector.ones()
    env = TaskLocalEnv(cv)
    assert target.check_invariant(env, "receive") is allowed
    assert target.check_invariant(env) is not allowed
    assert target.check_invariant(env, "enqueue") is not allowed

    if allowed:
        Computer().drive(env, target, "receive", payload="allowed")
        assert target.received == ["allowed"]
    else:
        with pytest.raises(AssertionError, match="Contention invariant violated"):
            Computer().drive(env, target, "receive", payload="blocked")
        assert not target.received


def test_inherited_methods_keep_declarations_and_overrides_fall_back_to_class():
    class Parent(Receiver):
        @requires_cv(FREE_CV)
        def receive(self, sig: Signal):
            super().receive(sig)

    @requires_cv(ContentionVector(local_irq=0))
    class Child(Parent):
        pass

    class Override(Child):
        def receive(self, sig: Signal):
            super().receive(sig)

    class Redeclared(Override):
        @requires_cv(FREE_CV)
        def receive(self, sig: Signal):
            super().receive(sig)

    cv = ContentionVector.ones()
    env = TaskLocalEnv(cv)
    parent = Parent("Parent")
    child = Child("Child")
    override = Override("Override")
    redeclared = Redeclared("Redeclared")

    assert not parent.check_invariant(env)
    assert not child.check_invariant(env)
    for target in (parent, child, redeclared):
        Computer().drive(env, target, "receive", payload="inherited")
        assert target.received == ["inherited"]

    with pytest.raises(AssertionError, match="violated domains: local_irq"):
        Computer().drive(env, override, "receive", payload="blocked")
    assert not override.received
    Computer().drive(
        TaskLocalEnv(ContentionVector(local_irq=0)),
        override,
        "receive",
        payload="class fallback",
    )
    assert override.received == ["class fallback"]


def test_multiple_inheritance_uses_the_actual_method_declaration():
    @requires_cv(FREE_CV)
    class Parent(Receiver):
        @requires_cv(EXCLUSIVE_CV)
        def receive(self, sig: Signal):
            super().receive(sig)

    class Left(Parent):
        def receive(self, sig: Signal):
            super().receive(sig)

    class Right(Parent):
        @requires_cv(ContentionVector(remote_irq=0))
        def receive(self, sig: Signal):
            super().receive(sig)

    class LeftFirst(Left, Right):
        pass

    class RightFirst(Right, Left):
        pass

    left = LeftFirst("Left")
    right = RightFirst("Right")
    cv = ContentionVector.ones()
    env = TaskLocalEnv(cv)
    Computer().drive(env, left, "receive", payload="class fallback")
    assert left.received == ["class fallback"]
    with pytest.raises(AssertionError, match="violated domains: remote_irq"):
        Computer().drive(env, right, "receive", payload="blocked")
    assert not right.received
    Computer().drive(
        TaskLocalEnv(ContentionVector(remote_irq=0)),
        right,
        "receive",
        payload="method declaration",
    )
    assert right.received == ["method declaration"]


def test_method_decorator_preserves_function_and_direct_calls_skip_checks():
    def receive(self: Receiver, sig: Signal) -> None:
        Receiver.receive(self, sig)

    original_signature = signature(receive)
    decorated = requires_cv(EXCLUSIVE_CV)(receive)
    assert decorated is receive
    assert signature(decorated) == original_signature

    @requires_cv(FREE_CV)
    class MethodReceiver(Receiver):
        receive = decorated

    target = MethodReceiver("Direct")
    signal = Signal(
        target, "receive", {"payload": "direct"}, TaskLocalEnv(FREE_CV), deque()
    )
    target.receive(signal)
    assert target.received == ["direct"]

    with pytest.raises(AssertionError, match="Contention invariant violated"):
        signal.handle()
    assert target.received == ["direct"]


@pytest.mark.parametrize("declaration", ["method", "class", "default"])
def test_diagnostics_report_the_selected_requirement(declaration, monkeypatch, capsys):
    @requires_cv(ContentionVector(remote_tasks=0))
    class DiagnosticReceiver(Receiver):
        @requires_cv(ContentionVector(local_irq=0))
        def receive(self, sig: Signal):
            super().receive(sig)

    if declaration == "default":
        target = Receiver("Target")
        action = "receive"
        requirement = EXCLUSIVE_CV
        domains = ["local_irq", "local_tasks", "remote_irq", "remote_tasks"]
    else:
        target = DiagnosticReceiver("Target")
        if declaration == "method":
            action = "receive"
            requirement = ContentionVector(local_irq=0)
            domains = ["local_irq"]
        else:
            action = "enqueue"
            requirement = ContentionVector(remote_tasks=0)
            domains = ["remote_tasks"]

    cv = ContentionVector.ones()
    env = TaskLocalEnv(cv)
    monkeypatch.setenv("DEBUG", "y")
    with pytest.raises(AssertionError) as exc_info:
        Computer().drive(env, target, action, payload="blocked")

    assert capsys.readouterr().err.splitlines() == [
        "    [DEBUG] Target.check_invariant:",
        f"        cv={cv}",
        f"        visibility={target.resolve_visibility(action)}",
        f"        requires_cv={requirement}",
    ]
    assert str(exc_info.value).splitlines() == [
        f"    Contention invariant violated for Target.{action}:",
        f"        violated domains: {', '.join(domains)}",
        f"        cv={cv}",
        f"        visibility={target.resolve_visibility(action)}",
        f"        requires_cv={requirement}",
    ]
    assert target.violated_domains(env, action) == domains
    assert not target.received
    assert not target.environments
    assert env.depth == 0

    class_requirement = (
        EXCLUSIVE_CV if declaration == "default" else ContentionVector(remote_tasks=0)
    )
    class_domains = domains if declaration == "default" else ["remote_tasks"]
    assert target.violated_domains(env) == class_domains
    formatted = target.format_invariant(env, "Inputs:", show_violations=True)
    assert f"requires_cv={class_requirement}" in formatted
    assert f"violated domains: {', '.join(class_domains)}" in formatted


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
