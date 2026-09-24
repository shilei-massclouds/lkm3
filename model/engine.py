from collections import deque
from dataclasses import dataclass


@dataclass
class Signal:
    target: System
    action: str

    def handle(self):
        action = getattr(self.target, self.action)
        action(self)


@dataclass
class System:
    pass


signals: deque[Signal] = deque()


def emit(target: System, action: str):
    signals.append(Signal(target, action))


def process() -> None:
    while signals:
        sig = signals.popleft()
        sig.handle()
