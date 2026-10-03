from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, ClassVar

from framework.sync import ContentionVector


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
    visibility: ContentionVector = field(
        default_factory=ContentionVector.ones, kw_only=True, repr=False
    )
    require_ce: ContentionVector = field(
        default_factory=ContentionVector.zeros, kw_only=True, repr=False
    )

    def drive(self, ce: ContentionVector, target: System, action: str, **kwargs):
        indent = "    " * Engine.depth
        print(f"{indent}{self}:")

        Engine.depth += 1
        try:
            engine = Engine(ce)
            engine.emit(target, action, **kwargs)
            engine.process()
        finally:
            Engine.depth -= 1

    def drive_all(
        self, ce: ContentionVector, targets: Iterable[System], action: str, **kwargs
    ):
        for target in targets:
            self.drive(ce, target, action, **kwargs)

    def acquire(self, ce: ContentionVector):
        if not self.check_invariant(ce):
            raise AssertionError(
                f"Contention invariant violated for {self}: "
                f"ce={ce}, visibility={self.visibility}, require_ce={self.require_ce}"
            )

    def release(self, ce: ContentionVector):
        pass

    def check_invariant(self, ce: ContentionVector) -> bool:
        effective_ce = ce.min(self.visibility)
        return effective_ce <= self.require_ce


@dataclass
class Engine:
    ce: ContentionVector
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
