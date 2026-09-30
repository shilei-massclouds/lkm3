from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Signal:
    target: System
    action: str
    args: dict[str, Any]
    engine: Engine

    def handle(self):
        action = getattr(self.target, self.action)
        action(self)


@dataclass
class System:
    pass


@dataclass
class Engine:
    signals: deque[Signal] = field(default_factory=deque)

    def emit(self, target: System, action: str, args: dict[str, Any]):
        print(f"{action} -> {target}")
        self.signals.append(Signal(target, action, args, self))

    def process(self):
        while self.signals:
            sig = self.signals.popleft()
            sig.handle()


def drive(target: System, action: str, **kwargs):
    engine = Engine()
    engine.emit(target, action, kwargs)
    engine.process()


def drive_all(targets: list[System], action: str, **kwargs):
    for target in targets:
        drive(target, action, **kwargs)
