"""Test Signal Sources and Dispatch"""

from dataclasses import dataclass, field

from engine import Engine, Signal, System, drive, drive_all
from systems.computer import Computer


@dataclass
class Receiver(System):
    name: str
    received: list[object] = field(default_factory=list)

    def __repr__(self):
        return self.name

    def receive(self, sig: Signal):
        self.received.append(sig.args["payload"])

    def enqueue(self, sig: Signal):
        sig.engine.emit(self, "receive", payload=sig.args["payload"])

    def relay(self, sig: Signal):
        drive(self, sig.args["recipient"], "enqueue", payload=sig.args["payload"])


def test_drive_source_and_nested_events(capsys):
    source = Computer()
    relay = Receiver("Relay")
    target = Receiver("Target")
    payload = object()

    drive(source, relay, "relay", recipient=target, payload=payload)

    assert len(target.received) == 1
    assert target.received[0] is payload
    assert not relay.received
    assert capsys.readouterr().out.splitlines() == [
        "Computer():",
        "    relay -> Relay",
        "    Relay:",
        "        enqueue -> Target",
        "        receive -> Target",
    ]
    assert Engine.depth == 0


def test_drive_all_source_and_generator(capsys):
    source = Computer()
    targets = [Receiver("First"), Receiver("Second")]
    payload = object()

    drive_all(source, (target for target in targets), "receive", payload=payload)

    for target in targets:
        assert len(target.received) == 1
        assert target.received[0] is payload
    assert capsys.readouterr().out.splitlines() == [
        "Computer():",
        "    receive -> First",
        "Computer():",
        "    receive -> Second",
    ]
    assert Engine.depth == 0
