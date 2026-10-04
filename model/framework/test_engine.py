"""Test Signal Sources and Dispatch"""

from dataclasses import dataclass, field

import pytest

from framework.engine import Engine, Signal, System, requires_cv
from framework.sync import ContentionVector
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
        self.environments.append(sig.engine.ce)
        self.received.append(sig.args["payload"])

    def enqueue(self, sig: Signal):
        self.environments.append(sig.engine.ce)
        sig.engine.emit(self, "receive", payload=sig.args["payload"])

    def relay(self, sig: Signal):
        self.environments.append(sig.engine.ce)
        self.drive(
            sig.engine.ce,
            sig.args["recipient"],
            "enqueue",
            payload=sig.args["payload"],
        )


def test_drive_source_and_nested_events(capsys):
    ce = ContentionVector.ones()
    source = Computer()
    relay = Receiver("Relay", require_cv=ContentionVector.ones())
    target = Receiver("Target", require_cv=ContentionVector.ones())
    payload = object()

    source.drive(ce, relay, "relay", recipient=target, payload=payload)

    assert len(target.received) == 1
    assert target.received[0] is payload
    assert not relay.received
    assert len(relay.environments) == 1
    assert relay.environments[0] is ce
    assert len(target.environments) == 2
    assert all(env is ce for env in target.environments)
    assert capsys.readouterr().out.splitlines() == [
        "Computer():",
        "    relay -> Relay",
        "    Relay:",
        "        enqueue -> Target",
        "        receive -> Target",
    ]
    assert Engine.depth == 0


def test_drive_all_source_and_generator(capsys):
    ce = ContentionVector.ones()
    source = Computer()
    targets = [
        Receiver("First", require_cv=ContentionVector.ones()),
        Receiver("Second", require_cv=ContentionVector.ones()),
    ]
    payload = object()

    source.drive_all(ce, (target for target in targets), "receive", payload=payload)

    for target in targets:
        assert len(target.received) == 1
        assert target.received[0] is payload
        assert len(target.environments) == 1
        assert target.environments[0] is ce
    assert capsys.readouterr().out.splitlines() == [
        "Computer():",
        "    receive -> First",
        "Computer():",
        "    receive -> Second",
    ]
    assert Engine.depth == 0


def test_signal_releases_environment_when_action_raises():
    ce = ContentionVector.ones()
    error = RuntimeError("action failed")
    calls: list[tuple[str, ContentionVector]] = []

    class FailingTarget(System):
        def acquire(self, ce: ContentionVector, action: str):
            calls.append(("acquire", ce))
            ce.local_irq = 0
            ce.local_tasks = 0
            ce.remote_irq = 0
            ce.remote_tasks = 0
            super().acquire(ce, action)

        def fail(self, sig: Signal):
            calls.append(("action", sig.engine.ce))
            assert sig.engine.ce.local_irq == 0
            raise error

        def release(self, ce: ContentionVector, action: str):
            calls.append(("release", ce))
            ce.local_irq = 1
            ce.local_tasks = 1
            ce.remote_irq = 1
            ce.remote_tasks = 1

    signal = Signal(FailingTarget(), "fail", {}, Engine(ce))

    with pytest.raises(RuntimeError) as exc_info:
        signal.handle()

    assert exc_info.value is error
    assert [phase for phase, _ in calls] == ["acquire", "action", "release"]
    assert all(env is ce for _, env in calls)
    assert ce.local_irq == ce.local_tasks == ce.remote_irq == ce.remote_tasks == 1


def test_system_defaults_require_exclusive_access():
    ce = ContentionVector.ones()
    system = System()

    assert system.visibility.local_irq == 1
    assert system.visibility.local_tasks == 1
    assert system.visibility.remote_irq == 1
    assert system.visibility.remote_tasks == 1
    assert system.require_cv.local_irq == 0
    assert system.require_cv.local_tasks == 0
    assert system.require_cv.remote_irq == 0
    assert system.require_cv.remote_tasks == 0
    assert not system.check_invariant(ce)

    ce.local_irq = 0
    ce.local_tasks = 0
    ce.remote_irq = 0
    ce.remote_tasks = 0
    assert system.check_invariant(ce)


def test_invariant_masks_visibility_and_checks_each_required_domain():
    ce = ContentionVector.ones()
    visibility = ContentionVector.zeros()
    visibility.remote_tasks = 1
    system = System(visibility=visibility)

    assert not system.check_invariant(ce)

    require_cv = ContentionVector.zeros()
    require_cv.remote_tasks = 1
    tolerant = System(visibility=visibility, require_cv=require_cv)
    assert tolerant.check_invariant(ce)
    assert not System(require_cv=require_cv).check_invariant(ce)
    assert System(visibility=ContentionVector.zeros()).check_invariant(ce)
    assert ce.local_irq == ce.local_tasks == ce.remote_irq == ce.remote_tasks == 1


def test_drive_stops_before_action_when_invariant_fails():
    ce = ContentionVector.ones()
    source = Computer()
    target = Receiver("Target")

    with pytest.raises(AssertionError, match="Contention invariant violated"):
        source.drive(ce, target, "receive", payload=object())

    assert not target.received
    assert not target.environments
    assert Engine.depth == 0


def test_requires_cv_default_controls_signal_dispatch():
    @requires_cv(ContentionVector(remote_irq=0))
    @dataclass
    class SharedReceiver(Receiver):
        pass

    target = SharedReceiver("Shared")
    ce = ContentionVector(remote_irq=0)
    payload = object()

    Computer().drive(ce, target, "receive", payload=payload)

    assert target.received == [payload]
    assert target.environments == [ce]
    with pytest.raises(AssertionError, match="require_cv="):
        Computer().drive(ContentionVector.ones(), target, "receive", payload=object())
    assert target.received == [payload]


def test_requires_cv_allows_explicit_instance_override():
    @requires_cv(ContentionVector.ones())
    @dataclass
    class SharedReceiver(Receiver):
        pass

    requirement = ContentionVector.zeros()
    visibility = ContentionVector.ones()
    target = SharedReceiver("Exclusive", visibility=visibility, require_cv=requirement)

    assert target.require_cv is requirement
    assert target.visibility is visibility
    assert not target.check_invariant(ContentionVector.ones())
    assert SharedReceiver("Shared").check_invariant(ContentionVector.ones())


def test_requires_cv_copies_defaults_without_changing_other_classes():
    default = ContentionVector(zero=True, local_irq=1, remote_tasks=1)

    @requires_cv(default)
    class SharedSystem(System):
        pass

    default.local_irq = 0
    first = SharedSystem()
    second = SharedSystem()
    first.require_cv.remote_tasks = 0

    assert first.require_cv is not second.require_cv
    assert second.require_cv is not default
    assert second.require_cv.local_irq == 1
    assert second.require_cv.local_tasks == 0
    assert second.require_cv.remote_irq == 0
    assert second.require_cv.remote_tasks == 1
    assert second.require_cv._remote_limit == 0
    assert SharedSystem().require_cv.remote_tasks == 1
    assert System().require_cv.local_irq == 0
    assert Receiver("Exclusive").require_cv.remote_tasks == 0


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

    ce = ContentionVector.ones()
    plain = PlainChild("plain")
    child = DataclassChild("child", 3)

    assert plain.check_invariant(ce)
    assert child.name == "child" and child.count == 3
    assert child.check_invariant(ce)
    assert not ExclusiveChild("exclusive").check_invariant(ce)
    assert SharedSystem("parent").check_invariant(ce)
    child.require_cv.local_irq = 0
    assert plain.require_cv.local_irq == 1
    assert DataclassChild("another", 1).require_cv.local_irq == 1


def test_requires_cv_supports_custom_initializers():
    @requires_cv(ContentionVector.ones())
    class SharedItem(CmdItem):
        pass

    item = SharedItem("earlycon", "sbi")

    assert item.key == "earlycon" and item.val == "sbi"
    assert item.check_invariant(ContentionVector.ones())
    assert not CmdItem("earlycon", "sbi").check_invariant(ContentionVector.ones())
    item.require_cv.local_irq = 0
    assert SharedItem("other", "value").require_cv.local_irq == 1
