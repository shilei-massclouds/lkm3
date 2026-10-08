"""Contention vectors and presets for environments and target visibility."""


# A vector is used either for environment contention and required safety
# boundaries, or for target visibility; these roles use separate named values.
class ContentionVector:
    """Signed contention levels, compared independently in each domain.

    Zero represents safety from exclusive access. Negative levels represent
    redundant protection and are also safe for exclusive requirements.
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
        return ContentionVector(
            local_irq=min(self.local_irq, other.local_irq),
            local_tasks=min(self.local_tasks, other.local_tasks),
            remote_irq=min(self.remote_irq, other.remote_irq),
            remote_tasks=min(self.remote_tasks, other.remote_tasks),
        )

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
