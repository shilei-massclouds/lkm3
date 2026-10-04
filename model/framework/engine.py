import sys
from collections import deque
from collections.abc import Callable, Iterable
from copy import copy
from dataclasses import dataclass, field, fields
from functools import wraps
from inspect import Parameter, signature
from os import getenv
from typing import Any, ClassVar

from framework.sync import ContentionVector


def env_enabled(name: str) -> bool:
    """Return whether the named environment variable enables an option."""
    return getenv(name, "").strip().lower() in {"y", "1", "true", "yes", "on"}


@dataclass
class Signal:
    target: System
    action: str
    args: dict[str, Any]
    engine: Engine

    def handle(self):
        action = getattr(self.target, self.action)
        self.target.acquire(self.engine.cv, self.action)
        try:
            action(self)
        finally:
            self.target.release(self.engine.cv, self.action)

    def chain(self, target: System, action: str, **kwargs):
        self.engine.emit(target, action, **kwargs)


@dataclass
class System:
    visibility: ContentionVector = field(
        default_factory=ContentionVector.ones, kw_only=True, repr=False
    )
    require_cv: ContentionVector = field(
        default_factory=ContentionVector.zeros, kw_only=True, repr=False
    )

    def drive(self, cv: ContentionVector, target: System, action: str, **kwargs):
        indent = "    " * Engine.depth
        print(f"{indent}{self}:")

        Engine.depth += 1
        try:
            engine = Engine(cv)
            engine.emit(target, action, **kwargs)
            engine.process()
        finally:
            Engine.depth -= 1

    def drive_all(
        self, cv: ContentionVector, targets: Iterable[System], action: str, **kwargs
    ):
        for target in targets:
            self.drive(cv, target, action, **kwargs)

    def acquire(self, cv: ContentionVector, action: str):
        assert self.check_invariant(cv), self.format_invariant(
            cv,
            f"Contention invariant violated for {self}.{action}:",
            show_violations=True,
        )

    def release(self, cv: ContentionVector, action: str):
        pass

    def check_invariant(self, cv: ContentionVector) -> bool:
        effective_cv = cv.min(self.visibility)
        if env_enabled("DEBUG"):
            print(
                self.format_invariant(cv, f"[DEBUG] {self}.check_invariant:"),
                file=sys.stderr,
            )
        return effective_cv <= self.require_cv

    def violated_domains(self, cv: ContentionVector) -> list[str]:
        """List domains whose visible contention exceeds their requirement."""
        effective_cv = cv.min(self.visibility)
        return [
            domain
            for domain in ("local_irq", "local_tasks", "remote_irq", "remote_tasks")
            if getattr(effective_cv, domain) > getattr(self.require_cv, domain)
        ]

    def format_invariant(
        self, cv: ContentionVector, header: str, *, show_violations: bool = False
    ) -> str:
        """Format the invariant inputs and optional violations with call indentation."""
        indent = "    " * Engine.depth
        violations = (
            f"{indent}    violated domains: {', '.join(self.violated_domains(cv))}\n"
            if show_violations
            else ""
        )
        return (
            f"{indent}{header}\n"
            f"{violations}"
            f"{indent}    cv={cv}\n"
            f"{indent}    visibility={self.visibility}\n"
            f"{indent}    require_cv={self.require_cv}"
        )


def requires_cv[S: System](
    default: ContentionVector,
) -> Callable[[type[S]], type[S]]:
    """Set a System subclass's default requirement; place above @dataclass.

    Each instance gets its own copy unless require_cv is passed explicitly.
    The default is also inherited by subclasses, including dataclasses.
    """
    if not isinstance(default, ContentionVector):
        raise TypeError("requires_cv expects a ContentionVector")
    template = copy(default)

    def decorate(cls: type[S]) -> type[S]:
        if not issubclass(cls, System):
            raise TypeError("requires_cv can only decorate System subclasses")

        # Copy field metadata so dataclass subclasses inherit the new factory
        # without changing the parent class's default.
        class_fields = {item.name: item for item in fields(cls)}
        requirement = copy(class_fields["require_cv"])
        requirement.default_factory = lambda: copy(template)
        class_fields["require_cv"] = requirement
        cls.__dataclass_fields__ = class_fields

        original_init = cls.__init__
        parameters = signature(original_init).parameters
        accepts_requirement = "require_cv" in parameters or any(
            parameter.kind == Parameter.VAR_KEYWORD for parameter in parameters.values()
        )

        @wraps(original_init)
        def init(self: S, *args: Any, **kwargs: Any):
            requirement = (
                kwargs.pop("require_cv") if "require_cv" in kwargs else copy(template)
            )
            if accepts_requirement:
                kwargs["require_cv"] = requirement
            original_init(self, *args, **kwargs)
            if not accepts_requirement:
                self.require_cv = requirement

        cls.__init__ = init
        return cls

    return decorate


@dataclass
class Engine:
    cv: ContentionVector
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
