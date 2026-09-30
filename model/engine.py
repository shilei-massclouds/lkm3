from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, ClassVar


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
    depth: ClassVar[int] = 0
    signals: deque[Signal] = field(default_factory=deque)

    def emit(self, target: System, action: str, **args):
        indent = "    " * Engine.depth
        print(f"{indent}{action} -> {target}")
        self.signals.append(Signal(target, action, args, self))

    def process(self):
        while self.signals:
            sig = self.signals.popleft()
            sig.handle()


def drive(source: System, target: System, action: str, **kwargs):
    indent = "    " * Engine.depth
    print(f"{indent}{source}:")

    Engine.depth += 1
    engine = Engine()
    engine.emit(target, action, **kwargs)
    engine.process()
    Engine.depth -= 1


def drive_all(source: System, targets: Iterable[System], action: str, **kwargs):
    for target in targets:
        drive(source, target, action, **kwargs)
