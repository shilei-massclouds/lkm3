"""Contention Utilities"""


class ContentionVector:
    local_irq: int
    local_tasks: int
    remote_irq: int
    remote_tasks: int
    _remote_limit: int

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
        self._remote_limit = default

    def __repr__(self):
        return (
            f"ContentionVector(local_irq={self.local_irq}, "
            f"local_tasks={self.local_tasks}, remote_irq={self.remote_irq}, "
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


class SyncPrimitive:
    pass


class LocalIrq(SyncPrimitive):
    def enable(self, cv: ContentionVector):
        cv.local_irq = 1

    def disable(self, cv: ContentionVector):
        cv.local_irq = 0


FREE_CV = ContentionVector.ones()
EXCLUSIVE_CV = ContentionVector.zeros()
