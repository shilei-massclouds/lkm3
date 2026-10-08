import sys
from collections import deque
from collections.abc import Callable, Iterable
from copy import copy
from dataclasses import dataclass, field
from os import getenv
from types import FunctionType
from typing import TYPE_CHECKING, Any, cast
from warnings import warn

from framework.contention import DOMAINS, EXCLUSIVE_CV, FULLSCOPE_CV, ContentionVector

if TYPE_CHECKING:
    from kernel.task import Task

_REQUIRES_CV_ATTR = "__requires_cv__"
_VISIBILITY_ATTR = "__visibility__"


def env_enabled(name: str) -> bool:
    """Return whether the named environment variable enables an option."""
    return getenv(name, "").strip().lower() in {"y", "1", "true", "yes", "on"}


@dataclass
class TaskLocalEnv:
    cv: ContentionVector = field(default_factory=ContentionVector.zeros)
    task: Task | None = field(default=None, repr=False)
    depth: int = 0
    signal_queues: list[deque[Signal]] = field(default_factory=list, repr=False)


def _emit(env: TaskLocalEnv, queue: deque[Signal], target: System, action: str, **args):
    indent = "    " * env.depth
    print(f"{indent}{action} -> {target}")
    queue.append(Signal(target, action, args, env, queue))


@dataclass
class Signal:
    target: System
    action: str
    args: dict[str, Any]
    env: TaskLocalEnv
    queue: deque[Signal] = field(repr=False)

    def handle(self):
        action = getattr(self.target, self.action)
        self.target.acquire(self.env, self.action)
        try:
            action(self)
        finally:
            self.target.release(self.env, self.action)

    def chain(self, target: System, action: str, **kwargs):
        _emit(self.env, self.queue, target, action, **kwargs)


@dataclass
class System:
    def resolve_requires_cv(self, action: str | None = None) -> ContentionVector:
        """Copy the method requirement, nearest class declaration, or default."""
        if action is not None:
            requirement = getattr(getattr(self, action), _REQUIRES_CV_ATTR, None)
            if requirement is not None:
                return copy(requirement)
        for cls in type(self).__mro__:
            requirement = cls.__dict__.get(_REQUIRES_CV_ATTR)
            if requirement is not None:
                return copy(requirement)
        return copy(EXCLUSIVE_CV)

    def resolve_visibility(self, action: str | None = None) -> ContentionVector:
        """Copy the method declaration, nearest class declaration, or full-scope default."""
        if action is not None:
            declaration = getattr(getattr(self, action), _VISIBILITY_ATTR, None)
            if declaration is not None:
                return copy(declaration)
        for cls in type(self).__mro__:
            declaration = cls.__dict__.get(_VISIBILITY_ATTR)
            if declaration is not None:
                return copy(declaration)
        return copy(FULLSCOPE_CV)

    def drive(self, env: TaskLocalEnv, target: System, action: str, **kwargs):
        """Finish this invocation's signal queue before returning to its caller."""
        depth = env.depth
        indent = "    " * depth
        print(f"{indent}{self}:")

        queue: deque[Signal] = deque()
        env.signal_queues.append(queue)
        env.depth = depth + 1
        try:
            _emit(env, queue, target, action, **kwargs)
            while queue:
                queue.popleft().handle()
        finally:
            env.signal_queues.pop()
            env.depth = depth

    def drive_all(
        self, env: TaskLocalEnv, targets: Iterable[System], action: str, **kwargs
    ):
        for target in targets:
            self.drive(env, target, action, **kwargs)

    def acquire(self, env: TaskLocalEnv, action: str):
        assert self.check_invariant(env, action), self.format_invariant(
            env,
            f"Contention invariant violated for {self}.{action}:",
            action,
            show_violations=True,
        )

    def release(self, env: TaskLocalEnv, action: str):
        pass

    def check_invariant(self, env: TaskLocalEnv, action: str | None = None) -> bool:
        if env_enabled("DEBUG"):
            debug_action = action or "check_invariant"
            print(
                self.format_invariant(env, f"[DEBUG] {self}.{debug_action}:", action),
                file=sys.stderr,
            )
        return not self.violated_domains(env, action)

    def violated_domains(
        self, env: TaskLocalEnv, action: str | None = None
    ) -> list[str]:
        """List visible domains with unsafe counts or mismatched protection."""
        visible = self.resolve_visibility(action)
        effective_cv = env.cv.min(visible)
        requirement = self.resolve_requires_cv(action)
        return [
            domain
            for domain in DOMAINS
            if getattr(effective_cv, domain) > getattr(requirement, domain)
            or (
                getattr(visible, domain) > getattr(requirement, domain)
                and not env.cv.protects(domain, self)
            )
        ]

    def format_invariant(
        self,
        env: TaskLocalEnv,
        header: str,
        action: str | None = None,
        *,
        show_violations: bool = False,
    ) -> str:
        """Format the invariant inputs and optional violations with call indentation."""
        indent = "    " * env.depth
        visibility = self.resolve_visibility(action)
        effective_cv = env.cv.min(visibility)
        vectors = {
            "environment": env.cv,
            "visibility": visibility,
            "effective": effective_cv,
        }
        widths = {
            domain: max(
                len(str(getattr(vector, domain))) for vector in vectors.values()
            )
            for domain in DOMAINS
        }
        rows = []
        for label, vector in vectors.items():
            values = ", ".join(
                f"{domain}={getattr(vector, domain):>{widths[domain]}}"
                for domain in DOMAINS
            )
            rows.append(f"{indent}    {label:<11} = ({values})")
        if show_violations:
            for domain in self.violated_domains(env, action):
                protections = ", ".join(
                    "None" if target is None else repr(target)
                    for target in env.cv.stacks[domain]
                )
                rows.append(f"{indent}    {domain} stack = [{protections}]")
        violations = (
            f"{indent}    violated domains: {', '.join(self.violated_domains(env, action))}\n"
            if show_violations
            else ""
        )
        return f"{indent}{header}\n{violations}" + "\n".join(rows)


def requires_cv[T: type[System] | Callable[..., Any]](
    requirement: ContentionVector,
) -> Callable[[T], T]:
    """Declare a copied requirement on a System subclass or instance method.

    Return the original object without wrapping constructors or method calls.
    Method declarations take precedence over class declarations during dispatch.
    Static methods, class methods, and properties are not supported.

    Deprecated migration interface; use SyncPrimitive and visibility instead.
    """
    warn(
        "requires_cv is deprecated; use SyncPrimitive and visibility instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    assert isinstance(requirement, ContentionVector), (
        "requires_cv expects a ContentionVector"
    )
    template = copy(requirement)

    def decorate(target: T) -> T:
        if isinstance(target, type):
            assert issubclass(target, System), (
                "requires_cv can only decorate System subclasses"
            )
        else:
            assert isinstance(target, FunctionType), (
                "requires_cv expects a System subclass or instance method"
            )
        setattr(target, _REQUIRES_CV_ATTR, copy(template))
        return cast(T, target)

    return decorate


def visibility[T: type[System] | Callable[..., Any]](
    declaration: ContentionVector,
) -> Callable[[T], T]:
    """Declare a copied visibility on a System subclass or instance method.

    Method declarations take precedence over class declarations. When no
    declaration is present, the default is ``FULLSCOPE_CV``.
    """
    assert isinstance(declaration, ContentionVector), (
        "visibility expects a ContentionVector"
    )
    template = copy(declaration)

    def decorate(target: T) -> T:
        if isinstance(target, type):
            assert issubclass(target, System), (
                "visibility can only decorate System subclasses"
            )
        else:
            assert isinstance(target, FunctionType), (
                "visibility expects a System subclass or instance method"
            )
        setattr(target, _VISIBILITY_ATTR, copy(template))
        return cast(T, target)

    return decorate


def terminate(msg: str):
    import sys

    print(msg)
    sys.exit(0)
