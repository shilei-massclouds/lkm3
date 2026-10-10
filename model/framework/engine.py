import sys
from collections import deque
from collections.abc import Callable, Iterable
from copy import copy
from dataclasses import dataclass, field
from os import getenv
from types import FunctionType
from typing import TYPE_CHECKING, Any, cast

from framework.contention import (
    DOMAINS,
    EXCLUSIVE_CV,
    FULLSCOPE_CV,
    TASKPRIVATE_CV,
    TRANSPARENT_CV,
    ContentionVector,
)

if TYPE_CHECKING:
    from kernel.task import Task

_VISIBILITY_ATTR = "__visibility__"
_PROTECTED_BY_ATTR = "__protected_by__"
_MISSING = object()


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

    def handle(self) -> Any:
        action = getattr(self.target, self.action)
        self.target.acquire(self.env, self.action)
        try:
            return action(self)
        finally:
            self.target.release(self.env, self.action)

    def chain(self, target: System, action: str, **kwargs):
        _emit(self.env, self.queue, target, action, **kwargs)


@dataclass
class System:
    def resolve_visibility(self, action: str | None = None) -> ContentionVector:
        """Copy declarations, then choose a default from the action name."""
        if action is not None:
            declaration = getattr(getattr(self, action), _VISIBILITY_ATTR, None)
            if declaration is not None:
                return copy(declaration)
        for cls in type(self).__mro__:
            declaration = cls.__dict__.get(_VISIBILITY_ATTR)
            if declaration is not None:
                return copy(declaration)
        if action is not None and not action.startswith("_"):
            return copy(TRANSPARENT_CV)
        return copy(FULLSCOPE_CV)

    def resolve_protected_by(self, action: str | None = None) -> tuple[object, ...]:
        """Resolve targets whose protection is required before an action."""
        if action is not None:
            declaration = getattr(getattr(self, action), _PROTECTED_BY_ATTR, _MISSING)
            if declaration is not _MISSING:
                return (declaration,)
        for cls in type(self).__mro__:
            declaration = cls.__dict__.get(_PROTECTED_BY_ATTR, _MISSING)
            if declaration is not _MISSING:
                return (declaration,)
        return ()

    def drive(self, env: TaskLocalEnv, target: System, action: str, **kwargs) -> Any:
        """Finish this invocation's signal queue before returning to its caller."""
        depth = env.depth
        indent = "    " * depth
        print(f"{indent}{self}:")

        queue: deque[Signal] = deque()
        env.signal_queues.append(queue)
        env.depth = depth + 1
        try:
            _emit(env, queue, target, action, **kwargs)
            result = queue.popleft().handle()
            while queue:
                queue.popleft().handle()
            return result
        finally:
            env.signal_queues.pop()
            env.depth = depth

    def drive_all(
        self, env: TaskLocalEnv, targets: Iterable[System], action: str, **kwargs
    ) -> list[Any]:
        return [self.drive(env, target, action, **kwargs) for target in targets]

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
        return [
            domain for domain in DOMAINS if self._violates_domain(env, domain, action)
        ]

    def _violates_domain(
        self,
        env: TaskLocalEnv,
        domain: str,
        action: str | None,
    ) -> bool:
        """Return whether one contention domain violates an action invariant."""
        visible = self.resolve_visibility(action)
        if getattr(visible, domain) == 0:
            return False
        effective_cv = env.cv.min(visible)
        if getattr(effective_cv, domain) > getattr(EXCLUSIVE_CV, domain):
            return True
        return not self._protection_satisfied(env, domain, action)

    def _protection_satisfied(
        self,
        env: TaskLocalEnv,
        domain: str,
        action: str | None,
    ) -> bool:
        """Return whether the action's protection requirement is satisfied."""
        protected_by = self.resolve_protected_by(action)
        return env.cv.is_protected(domain, self, protected_by)

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

    def task_private_enter(self):
        return self

    def task_private_exit(self, exc_type, exc_value, traceback):
        pass

    def decorate(target: T) -> T:
        if isinstance(target, type):
            assert issubclass(target, System), (
                "visibility can only decorate System subclasses"
            )
            if declaration is TASKPRIVATE_CV:
                if not hasattr(target, "__enter__"):
                    type.__setattr__(target, "__enter__", task_private_enter)
                if not hasattr(target, "__exit__"):
                    type.__setattr__(target, "__exit__", task_private_exit)
        else:
            assert isinstance(target, FunctionType), (
                "visibility expects a System subclass or instance method"
            )
        setattr(target, _VISIBILITY_ATTR, copy(template))
        return cast(T, target)

    return decorate


def protected_by[T: type[System] | Callable[..., Any]](
    target: object,
) -> Callable[[T], T]:
    """Declare a target whose protection an action requires.

    The target is required in every visible domain and can also satisfy the
    action's own target boundary when the action is not transparent.
    """

    def decorate(declaration: T) -> T:
        if isinstance(declaration, type):
            assert issubclass(declaration, System), (
                "protected_by can only decorate System subclasses"
            )
        else:
            assert isinstance(declaration, FunctionType), (
                "protected_by expects a System subclass or instance method"
            )
        setattr(declaration, _PROTECTED_BY_ATTR, target)
        return cast(T, declaration)

    return decorate


def terminate(msg: str):
    import sys

    print(msg)
    sys.exit(0)
