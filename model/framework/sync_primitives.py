"""Synchronization primitives and scoped guards for contention adjustments."""

from types import TracebackType
from typing import Self

from framework.contention import ContentionVector


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
