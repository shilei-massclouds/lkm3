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
    ce = ContentionEnv()
    source = Computer()
    relay = Receiver("Relay")
    target = Receiver("Target")
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
    ce = ContentionEnv()
    source = Computer()
    targets = [Receiver("First"), Receiver("Second")]
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
    ce = ContentionEnv()
    error = RuntimeError("action failed")
    calls: list[tuple[str, ContentionEnv]] = []

    class FailingTarget(System):
        def acquire(self, ce: ContentionEnv):
            calls.append(("acquire", ce))
            ce.local_irq = 0

        def fail(self, sig: Signal):
            calls.append(("action", sig.engine.ce))
            assert sig.engine.ce.local_irq == 0
            raise error

        def release(self, ce: ContentionEnv):
            calls.append(("release", ce))
            ce.local_irq = 1

    signal = Signal(FailingTarget(), "fail", {}, Engine(ce))

    with pytest.raises(RuntimeError) as exc_info:
        signal.handle()

    assert exc_info.value is error
    assert [phase for phase, _ in calls] == ["acquire", "action", "release"]
    assert all(env is ce for _, env in calls)
    assert ce.local_irq == 1
