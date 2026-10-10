"""Synchronization primitives and scoped guards for contention adjustments."""

from dataclasses import dataclass
from types import TracebackType
from typing import Self

from framework.contention import DOMAINS, ContentionVector


class SyncPrimitive:
    pass


@dataclass(frozen=True)
class IrqFlags:
    """The saved IRQ contention level and its protection stack."""

    level: int
    stack: tuple[object | None, ...]


class LocalIrq(SyncPrimitive):
    """Adjust local IRQ contention by one, allowing negative levels."""

    def enable(self, cv: ContentionVector):
        cv.expose("local_irq")

    def disable(self, cv: ContentionVector):
        cv.protect(None, "local_irq")

    def save(self, cv: ContentionVector) -> IrqFlags:
        """Save the IRQ level and stack, then establish global protection."""
        flags = IrqFlags(cv.local_irq, tuple(cv.stacks["local_irq"]))
        self.disable(cv)
        return flags

    def restore(self, cv: ContentionVector, flags: IrqFlags):
        stack = cv.stacks["local_irq"]
        saved_depth = len(flags.stack)
        assert len(stack) >= saved_depth and all(
            current is saved for current, saved in zip(stack[:saved_depth], flags.stack)
        ), "saved IRQ protection is no longer held"
        assert all(target is None for target in stack[saved_depth:]), (
            "cannot restore IRQ state under target protection"
        )
        cv.local_irq = flags.level
        stack[:] = flags.stack


class Preemption(SyncPrimitive):
    """Adjust local task contention for preemption, allowing negative levels."""

    def enable(self, cv: ContentionVector):
        cv.expose("local_tasks")

    def disable(self, cv: ContentionVector):
        cv.protect(None, "local_tasks")


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

    def __init__(self, target: object | None):
        self.target = target

    def lock(self, cv: ContentionVector):
        cv.protect(self.target, "remote_irq", "remote_tasks")

    def unlock(self, cv: ContentionVector):
        cv.unprotect(self.target, "remote_irq", "remote_tasks")


class GuardBusyWaitLock(BusyWaitLock):
    """Reduce remote contention for a guarded busy-wait lock and restore it."""

    def __init__(self, cv: ContentionVector, target: object | None):
        super().__init__(target)
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


class AtomicReserve(SyncPrimitive):
    """Atomically reserve one resource from a set of equivalent resources.

    A successful reservation establishes exclusive access to the reserved
    resource in every contention domain. Unlike a busy-wait lock, contenders
    can reserve different resources and do not wait for this reservation to be
    released before making progress.
    """

    def __init__(self, target: object | None):
        self.target = target

    def acquire(self, cv: ContentionVector):
        cv.protect(self.target, *DOMAINS)

    def release(self, cv: ContentionVector):
        cv.unprotect(self.target, *DOMAINS)


class GuardAtomicReserve(AtomicReserve):
    """Establish and release an atomic reservation around a guarded block."""

    def __init__(self, cv: ContentionVector, target: object | None):
        super().__init__(target)
        self.cv = cv

    def __enter__(self) -> Self:
        self.acquire(self.cv)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release(self.cv)


class RcuReadSide(SyncPrimitive):
    """Model the protection held while reading an RCU-published target.

    This primitive records only the current read-side nesting in the
    contention vector. It does not wait for writers, acquire a lock, or model
    write-side synchronization.
    """

    def __init__(self, target: object | None):
        self.target = target

    def acquire(self, cv: ContentionVector):
        cv.protect(self.target, *DOMAINS)

    def release(self, cv: ContentionVector):
        cv.unprotect(self.target, *DOMAINS)


class GuardRcuReadSide(RcuReadSide):
    """Hold an RCU read-side protection for a guarded block."""

    def __init__(self, cv: ContentionVector, target: object | None):
        super().__init__(target)
        self.cv = cv

    def __enter__(self) -> Self:
        self.acquire(self.cv)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release(self.cv)


class BusyWaitPreemption(SyncPrimitive):
    """Combine a busy-wait lock with local preemption protection.

    Preemption is disabled before acquisition and enabled after release.
    Local IRQ contention remains unchanged.
    """

    def __init__(self, target: object | None):
        self._preemption = Preemption()
        self._lock = BusyWaitLock(target)

    def lock(self, cv: ContentionVector) -> None:
        self._preemption.disable(cv)
        self._lock.lock(cv)

    def unlock(self, cv: ContentionVector) -> None:
        self._lock.unlock(cv)
        self._preemption.enable(cv)


class GuardBusyWaitPreemption(BusyWaitPreemption):
    """Acquire a BusyWaitPreemption lock for a block and release it on exit."""

    def __init__(self, cv: ContentionVector, target: object | None):
        super().__init__(target)
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


class BusyWaitIrqSave(SyncPrimitive):
    """Combine a busy-wait lock with saved local IRQ protection.

    IRQ state is saved before acquisition and restored after release. Each
    acquisition returns its flags to the caller. Local task contention remains
    unchanged.
    """

    def __init__(self, target: object | None):
        self._irq = LocalIrq()
        self._lock = BusyWaitLock(target)

    def lock(self, cv: ContentionVector) -> IrqFlags:
        flags = self._irq.save(cv)
        self._lock.lock(cv)
        return flags

    def unlock(self, cv: ContentionVector, flags: IrqFlags) -> None:
        self._lock.unlock(cv)
        self._irq.restore(cv, flags)


class GuardBusyWaitIrqSave(BusyWaitIrqSave):
    """Acquire a BusyWaitIrqSave lock for a block and restore its IRQ flags."""

    def __init__(self, cv: ContentionVector, target: object | None):
        super().__init__(target)
        self.cv = cv
        self._flags: IrqFlags

    def __enter__(self) -> Self:
        self._flags = self.lock(self.cv)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.unlock(self.cv, self._flags)


class BusyWaitIrqSavePreemption(SyncPrimitive):
    """Combine a busy-wait lock, saved IRQ state and preemption protection.

    Follow __raw_spin_lock_irqsave and __raw_spin_unlock_irqrestore: save IRQ
    state, disable preemption and acquire the lock; then release the lock,
    restore IRQ state and enable preemption. Each acquisition returns its flags
    to the caller.
    """

    def __init__(self, target: object | None):
        self._irq = LocalIrq()
        self._preemption = Preemption()
        self._lock = BusyWaitLock(target)

    def lock(self, cv: ContentionVector) -> IrqFlags:
        flags = self._irq.save(cv)
        self._preemption.disable(cv)
        self._lock.lock(cv)
        return flags

    def unlock(self, cv: ContentionVector, flags: IrqFlags) -> None:
        self._lock.unlock(cv)
        self._irq.restore(cv, flags)
        self._preemption.enable(cv)


class GuardBusyWaitIrqSavePreemption(BusyWaitIrqSavePreemption):
    """Acquire the combined lock for a block and restore its protection on exit."""

    def __init__(self, cv: ContentionVector, target: object | None):
        super().__init__(target)
        self.cv = cv
        self._flags: IrqFlags

    def __enter__(self) -> Self:
        self._flags = self.lock(self.cv)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.unlock(self.cv, self._flags)


class LocalMultiTasks(SyncPrimitive):
    """Model the one-way transition from a single task to local multitasking."""

    def enable(self, cv: ContentionVector):
        cv.expose("local_tasks")


class RemoteCpus(SyncPrimitive):
    def enable(self, cv: ContentionVector):
        cv.expose("remote_irq", "remote_tasks")


class GuardLocalIrq(LocalIrq):
    """Reduce local IRQ contention by one and restore its saved value on exit."""

    def __init__(self, cv: ContentionVector):
        self.cv = cv
        self._flags: IrqFlags

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

    def __init__(self, target: object | None):
        self.target = target

    def lock(self, cv: ContentionVector):
        cv.protect(self.target, "local_tasks", "remote_tasks")

    def unlock(self, cv: ContentionVector):
        cv.unprotect(self.target, "local_tasks", "remote_tasks")


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
        cv.protect(self.target, "local_irq", "remote_irq")

    def unlock(self, cv: ContentionVector):
        cv.unprotect(self.target, "local_irq", "remote_irq")
        super().unlock(cv)


class GuardYieldLock(YieldLock):
    """Acquire a YieldLock for a guarded block and release it on exit."""

    def __init__(self, cv: ContentionVector, target: object | None):
        super().__init__(target)
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

    def __init__(self, cv: ContentionVector, target: object | None):
        super().__init__(target)
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
