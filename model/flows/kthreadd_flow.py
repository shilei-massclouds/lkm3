"""Task 2 waits for kernel-thread requests, currently omitted from the model."""

from dataclasses import dataclass

from flows.task_flow import TaskFlow
from framework.engine import Signal, requires_cv
from framework.sync import ContentionVector


@requires_cv(ContentionVector(zero=True, local_irq=1, local_tasks=1))
@dataclass
class KthreaddFlow(TaskFlow):
    def wait_for_work(self, sig: Signal):
        assert sig.env.task is not None
        scheduler = sig.env.task.require_scheduler()
        while True:
            self.drive(sig.env, scheduler, "schedule", block=True)
