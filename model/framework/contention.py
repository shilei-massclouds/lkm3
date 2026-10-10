"""Contention vectors and presets for environments and target visibility."""

from typing import Self

DOMAINS = ("local_irq", "local_tasks", "remote_irq", "remote_tasks")


# A vector is used either for environment contention and required safety
# boundaries, or for target visibility; these roles use separate named values.
class ContentionVector:
    """Signed contention levels, compared independently in each domain.

    Protection stacks record the objects protected in each domain. ``None``
    represents global protection, including initially absent competitors.
    Negative levels represent redundant protection.
    """

    local_irq: int
    local_tasks: int
    remote_irq: int
    remote_tasks: int

    def __init__(
        self,
        zero: bool = False,
        *,
        local_irq: int | None = None,
        local_tasks: int | None = None,
        remote_irq: int | None = None,
        remote_tasks: int | None = None,
    ):
        default = 0 if zero else 1
        self.local_irq = default if local_irq is None else local_irq
        self.local_tasks = default if local_tasks is None else local_tasks
        self.remote_irq = default if remote_irq is None else remote_irq
        self.remote_tasks = default if remote_tasks is None else remote_tasks
        self.stacks: dict[str, list[object | None]] = {
            domain: [None] * max(0, 1 - getattr(self, domain)) for domain in DOMAINS
        }

    def __copy__(self) -> Self:
        """Copy counts and stacks, preserving the identity of protected objects."""
        result = type(self)(**{domain: getattr(self, domain) for domain in DOMAINS})
        result.stacks = {domain: list(self.stacks[domain]) for domain in DOMAINS}
        return result

    def protect(self, target: object | None, *domains: str) -> None:
        """Reduce contention and push the protected target in each domain."""
        for domain in domains:
            self.stacks[domain].append(target)
            setattr(self, domain, getattr(self, domain) - 1)

    def unprotect(self, target: object | None, *domains: str) -> None:
        """Release protection in stack order and increase contention."""
        for domain in domains:
            stack = self.stacks[domain]
            assert stack and stack[-1] is target, (
                f"protection release out of order for {domain}"
            )
        for domain in domains:
            self.stacks[domain].pop()
            setattr(self, domain, getattr(self, domain) + 1)

    def expose(self, *domains: str) -> None:
        """Enable competitors, removing any surrounding global protection."""
        for domain in domains:
            stack = self.stacks[domain]
            assert not stack or stack[-1] is None, (
                f"cannot enable competitors under target protection for {domain}"
            )
        for domain in domains:
            if self.stacks[domain]:
                self.stacks[domain].pop()
            setattr(self, domain, getattr(self, domain) + 1)

    def is_protected(
        self,
        domain: str,
        target: object,
        protected_by: tuple[object, ...] = (),
    ) -> bool:
        """Check global, class-level, or exact-object protection.

        A class placed on a protection stack protects instances of that class
        and its subclasses. An explicitly declared class-level dependency also
        matches its class stack entry. Other stack entries retain identity
        semantics so unrelated objects with equal values are never treated as
        protected.
        """
        return any(
            protected is None
            or (
                isinstance(protected, type)
                and (
                    isinstance(target, protected)
                    or any(protected is declared for declared in protected_by)
                )
            )
            or protected is target
            for protected in self.stacks[domain]
        )

    def __repr__(self) -> str:
        return (
            f"(local_irq={self.local_irq}, "
            f"local_tasks={self.local_tasks}, "
            f"remote_irq={self.remote_irq}, "
            f"remote_tasks={self.remote_tasks})"
        )

    @staticmethod
    def ones() -> ContentionVector:
        return ContentionVector()

    @staticmethod
    def zeros() -> ContentionVector:
        return ContentionVector(zero=True)

    def min(self, other: ContentionVector) -> ContentionVector:
        """Return the minimum in each domain without changing either input."""
        result = ContentionVector(
            local_irq=min(self.local_irq, other.local_irq),
            local_tasks=min(self.local_tasks, other.local_tasks),
            remote_irq=min(self.remote_irq, other.remote_irq),
            remote_tasks=min(self.remote_tasks, other.remote_tasks),
        )
        # Numerical projections do not establish runtime protection.
        result.stacks = {domain: [] for domain in DOMAINS}
        return result

    def __le__(self, other: ContentionVector) -> bool:
        if not isinstance(other, ContentionVector):
            return NotImplemented
        return (
            self.local_irq <= other.local_irq
            and self.local_tasks <= other.local_tasks
            and self.remote_irq <= other.remote_irq
            and self.remote_tasks <= other.remote_tasks
        )


# Environment and requires_cv defaults.
FREE_CV = ContentionVector.ones()
EXCLUSIVE_CV = ContentionVector.zeros()

# Visibility declarations. A transparent target is a convenience wrapper;
# its nested actions provide their own contention requirements.
TRANSPARENT_CV = ContentionVector.zeros()
# A task-private target is visible only to its owning task.
TASKPRIVATE_CV = ContentionVector.zeros()
FULLSCOPE_CV = ContentionVector.ones()
CPUSCOPE_CV = ContentionVector(local_irq=1, local_tasks=1, remote_irq=0, remote_tasks=0)
TASKSCOPE_CV = ContentionVector(
    local_irq=0, local_tasks=1, remote_irq=0, remote_tasks=1
)
IRQSCOPE_CV = ContentionVector(local_irq=1, local_tasks=0, remote_irq=1, remote_tasks=0)
