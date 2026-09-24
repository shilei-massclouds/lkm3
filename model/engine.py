from collections import deque
from dataclasses import dataclass, field


@dataclass
class Signal:
    target: System
    action: str
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

    def emit(self, target: System, action: str):
        self.signals.append(Signal(target, action, self))

    def process(self):
        while self.signals:
            sig = self.signals.popleft()
            sig.handle()


def drive(target: System, action: str):
    engine = Engine()
    engine.emit(target, action)
    engine.process()
