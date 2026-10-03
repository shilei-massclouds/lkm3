"""Test Signal Sources and Dispatch"""

from dataclasses import dataclass, field

import pytest

from framework.engine import Engine, Signal, System
from framework.sync import ContentionEnv
from systems.computer import Computer


@dataclass
class Receiver(System):
    name: str
    received: list[object] = field(default_factory=list)
    environments: list[ContentionEnv] = field(default_factory=list)

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
    ce = ContentionEnv.ones()
    source = Computer()
    relay = Receiver("Relay", require_ce=ContentionEnv.ones())
    target = Receiver("Target", require_ce=ContentionEnv.ones())
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
    ce = ContentionEnv.ones()
    source = Computer()
    targets = [
        Receiver("First", require_ce=ContentionEnv.ones()),
        Receiver("Second", require_ce=ContentionEnv.ones()),
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
    ce = ContentionEnv.ones()
    error = RuntimeError("action failed")
    calls: list[tuple[str, ContentionEnv]] = []

    class FailingTarget(System):
        def acquire(self, ce: ContentionEnv):
            calls.append(("acquire", ce))
            ce.local_irq = 0
            ce.local_tasks = 0
            ce.remote_irq = 0
            ce.remote_tasks = 0
            super().acquire(ce)

        def fail(self, sig: Signal):
            calls.append(("action", sig.engine.ce))
            assert sig.engine.ce.local_irq == 0
            raise error

        def release(self, ce: ContentionEnv):
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
    ce = ContentionEnv.ones()
    system = System()

    assert system.visibility.local_irq == 1
    assert system.visibility.local_tasks == 1
    assert system.visibility.remote_irq == 1
    assert system.visibility.remote_tasks == 1
    assert system.require_ce.local_irq == 0
    assert system.require_ce.local_tasks == 0
    assert system.require_ce.remote_irq == 0
    assert system.require_ce.remote_tasks == 0
    assert not system.check_invariant(ce)

    ce.local_irq = 0
    ce.local_tasks = 0
    ce.remote_irq = 0
    ce.remote_tasks = 0
    assert system.check_invariant(ce)


def test_invariant_masks_visibility_and_checks_each_required_domain():
    ce = ContentionEnv.ones()
    visibility = ContentionEnv.zeros()
    visibility.remote_tasks = 1
    system = System(visibility=visibility)

    assert not system.check_invariant(ce)

    require_ce = ContentionEnv.zeros()
    require_ce.remote_tasks = 1
    tolerant = System(visibility=visibility, require_ce=require_ce)
    assert tolerant.check_invariant(ce)
    assert not System(require_ce=require_ce).check_invariant(ce)
    assert System(visibility=ContentionEnv.zeros()).check_invariant(ce)
    assert ce.local_irq == ce.local_tasks == ce.remote_irq == ce.remote_tasks == 1


def test_drive_stops_before_action_when_invariant_fails():
    ce = ContentionEnv.ones()
    source = Computer()
    target = Receiver("Target")

    with pytest.raises(AssertionError, match="Contention invariant violated"):
        source.drive(ce, target, "receive", payload=object())

    assert not target.received
    assert not target.environments
    assert Engine.depth == 0
