from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, ClassVar

from sync import ContentionEnv


@dataclass
class Signal:
    target: System
    action: str
    args: dict[str, Any]
    engine: Engine

    def handle(self):
        action = getattr(self.target, self.action)
        self.target.acquire(self.engine.ce)
        try:
            action(self)
        finally:
            self.target.release(self.engine.ce)

    def chain(self, target: System, action: str, **kwargs):
        self.engine.emit(target, action, **kwargs)


@dataclass
class System:
    def drive(self, ce: ContentionEnv, target: System, action: str, **kwargs):
        indent = "    " * Engine.depth
        print(f"{indent}{self}:")

        Engine.depth += 1
        engine = Engine(ce)
        engine.emit(target, action, **kwargs)
        engine.process()
        Engine.depth -= 1

    def drive_all(
        self, ce: ContentionEnv, targets: Iterable[System], action: str, **kwargs
    ):
        for target in targets:
            self.drive(ce, target, action, **kwargs)

    def acquire(self, ce: ContentionEnv):
        pass

    def release(self, ce: ContentionEnv):
        pass


@dataclass
class Engine:
    ce: ContentionEnv
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
