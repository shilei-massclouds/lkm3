"""Contention Utilities"""

from types import TracebackType
from typing import Self


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


class SyncPrimitive:
    pass


class LocalIrq(SyncPrimitive):
    """Adjust local IRQ contention by one, allowing negative levels."""

    def enable(self, cv: ContentionVector):
        cv.local_irq += 1

    def disable(self, cv: ContentionVector):
        cv.local_irq -= 1

    def save(self, cv: ContentionVector) -> int:
        """Save local IRQ contention and reduce it by one."""
        flags = cv.local_irq
        self.disable(cv)
        return flags

    def restore(self, cv: ContentionVector, flags: int):
        cv.local_irq = flags


class Preemption(SyncPrimitive):
    """Adjust local task contention for preemption, allowing negative levels."""

    def enable(self, cv: ContentionVector):
        cv.local_tasks += 1

    def disable(self, cv: ContentionVector):
        cv.local_tasks -= 1


class GuardPreemption(Preemption):
    """Reduce local task contention by one and restore it on exit."""

    def __init__(self, cv: ContentionVector):
        self.cv = cv

    def __enter__(self) -> Self:
        self.disable(self.cv)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.enable(self.cv)


class BusyWaitLock(SyncPrimitive):
    """Reduce remote contention while a busy-wait lock is held.

    Local IRQ and task contention remain unchanged because a local interrupt or
    task that preempts the owner must not busy-wait on its lock.
    """

    def lock(self, cv: ContentionVector):
        cv.remote_irq -= 1
        cv.remote_tasks -= 1

    def unlock(self, cv: ContentionVector):
        cv.remote_irq += 1
        cv.remote_tasks += 1


class GuardBusyWaitLock(BusyWaitLock):
    """Reduce remote contention for a guarded busy-wait lock and restore it."""

    def __init__(self, cv: ContentionVector):
        self.cv = cv

    def __enter__(self) -> Self:
        self.lock(self.cv)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.unlock(self.cv)


class LocalMultiTasks(SyncPrimitive):
    """Model the one-way transition from a single task to local multitasking."""

    def enable(self, cv: ContentionVector):
        cv.local_tasks += 1


class RemoteCpus(SyncPrimitive):
    def enable(self, cv: ContentionVector):
        cv.remote_irq += 1
        cv.remote_tasks += 1


class GuardLocalIrq(LocalIrq):
    """Reduce local IRQ contention by one and restore its saved value on exit."""

    def __init__(self, cv: ContentionVector):
        self.cv = cv
        self._flags: int

    def __enter__(self) -> Self:
        self._flags = self.save(self.cv)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.restore(self.cv, self._flags)


class YieldLock(SyncPrimitive):
    """Model a lock whose task contenders yield while waiting.

    Holding the lock reduces local and remote task contention. IRQ contention
    remains unchanged because the yielding operation is for task context.
    """

    def lock(self, cv: ContentionVector):
        cv.local_tasks -= 1
        cv.remote_tasks -= 1

    def unlock(self, cv: ContentionVector):
        cv.local_tasks += 1
        cv.remote_tasks += 1


class YieldTryLock(YieldLock):
    """Model yielding acquisition for tasks and nonblocking acquisition for IRQs.

    Task contenders yield while waiting. IRQ contenders try once and give up
    acquiring the lock on failure, without yielding or spinning. An IRQ therefore
    cannot deadlock by waiting on a lock held by the context it interrupted.

    The model follows the current task, so only lock/unlock are modeled; the
    IRQ-side try operation is outside its view. Holding the lock reduces both
    task and IRQ contention without disabling IRQs.
    """

    def lock(self, cv: ContentionVector):
        super().lock(cv)
        cv.local_irq -= 1
        cv.remote_irq -= 1

    def unlock(self, cv: ContentionVector):
        cv.local_irq += 1
        cv.remote_irq += 1
        super().unlock(cv)


class GuardYieldLock(YieldLock):
    """Acquire a YieldLock for a guarded block and release it on exit."""

    def __init__(self, cv: ContentionVector):
        self.cv = cv

    def __enter__(self) -> Self:
        self.lock(self.cv)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.unlock(self.cv)


class GuardYieldTryLock(YieldTryLock):
    """Acquire a YieldTryLock for a guarded block and release it on exit."""

    def __init__(self, cv: ContentionVector):
        self.cv = cv

    def __enter__(self) -> Self:
        self.lock(self.cv)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.unlock(self.cv)


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
