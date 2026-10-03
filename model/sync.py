"""Contention Utilities"""


class ContentionEnv:
    local_irq: int
    local_tasks: int
    remote_irq: int
    remote_tasks: int
    _remote_limit: int

    def __init__(self, zero=False):
        if zero:
            self.local_irq = 0
            self.local_tasks = 0
            self.remote_irq = 0
            self.remote_tasks = 0
            self._remote_limit = 0
        else:
            self.local_irq = 1
            self.local_tasks = 1
            self.remote_irq = 1
            self.remote_tasks = 1
            self._remote_limit = 1

    def acquire(self, sp: SyncPrimitive):
        pass

    def release(self, sp: SyncPrimitive):
        pass


class SyncPrimitive:
    pass
