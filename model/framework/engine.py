import sys
from collections import deque
from collections.abc import Callable, Iterable
from copy import copy
from dataclasses import dataclass, field
from os import getenv
from types import FunctionType
from typing import Any, ClassVar, cast

from framework.sync import EXCLUSIVE_CV, ContentionVector

_REQUIRE_CV_ATTR = "__require_cv__"


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

    def resolve_require_cv(self, action: str | None = None) -> ContentionVector:
        """Copy the method requirement, nearest class declaration, or default."""
        if action is not None:
            requirement = getattr(getattr(self, action), _REQUIRE_CV_ATTR, None)
            if requirement is not None:
                return copy(requirement)
        for cls in type(self).__mro__:
            requirement = cls.__dict__.get(_REQUIRE_CV_ATTR)
            if requirement is not None:
                return copy(requirement)
        return copy(EXCLUSIVE_CV)

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
        assert self.check_invariant(cv, action), self.format_invariant(
            cv,
            f"Contention invariant violated for {self}.{action}:",
            action,
            show_violations=True,
        )

    def release(self, cv: ContentionVector, action: str):
        pass

    def check_invariant(self, cv: ContentionVector, action: str | None = None) -> bool:
        effective_cv = cv.min(self.visibility)
        requirement = self.resolve_require_cv(action)
        if env_enabled("DEBUG"):
            print(
                self.format_invariant(cv, f"[DEBUG] {self}.check_invariant:", action),
                file=sys.stderr,
            )
        return effective_cv <= requirement

    def violated_domains(
        self, cv: ContentionVector, action: str | None = None
    ) -> list[str]:
        """List domains whose visible contention exceeds their requirement."""
        effective_cv = cv.min(self.visibility)
        requirement = self.resolve_require_cv(action)
        return [
            domain
            for domain in ("local_irq", "local_tasks", "remote_irq", "remote_tasks")
            if getattr(effective_cv, domain) > getattr(requirement, domain)
        ]

    def format_invariant(
        self,
        cv: ContentionVector,
        header: str,
        action: str | None = None,
        *,
        show_violations: bool = False,
    ) -> str:
        """Format the invariant inputs and optional violations with call indentation."""
        indent = "    " * Engine.depth
        violations = (
            f"{indent}    violated domains: {', '.join(self.violated_domains(cv, action))}\n"
            if show_violations
            else ""
        )
        return (
            f"{indent}{header}\n"
            f"{violations}"
            f"{indent}    cv={cv}\n"
            f"{indent}    visibility={self.visibility}\n"
            f"{indent}    require_cv={self.resolve_require_cv(action)}"
        )


def requires_cv[T: type[System] | Callable[..., Any]](
    requirement: ContentionVector,
) -> Callable[[T], T]:
    """Declare a copied requirement on a System subclass or instance method.

    Return the original object without wrapping constructors or method calls.
    Method declarations take precedence over class declarations during dispatch.
    Static methods, class methods, and properties are not supported.
    """
    if not isinstance(requirement, ContentionVector):
        raise TypeError("requires_cv expects a ContentionVector")
    template = copy(requirement)

    def decorate(target: T) -> T:
        if isinstance(target, type):
            if not issubclass(target, System):
                raise TypeError("requires_cv can only decorate System subclasses")
        elif not isinstance(target, FunctionType):
            raise TypeError("requires_cv expects a System subclass or instance method")
        setattr(target, _REQUIRE_CV_ATTR, copy(template))
        return cast(T, target)

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
