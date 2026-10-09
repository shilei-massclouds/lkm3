"""Task 2 waits for kernel-thread requests, currently omitted from the model."""

from dataclasses import dataclass

from flows.task_flow import TaskFlow
from framework.engine import Signal


@dataclass
class KthreaddFlow(TaskFlow):
    def _wait_for_work(self, sig: Signal):
        assert sig.env.task is not None
        scheduler = sig.env.task._scheduler()
        while True:
            self.drive(sig.env, scheduler, "_schedule", block=True)
