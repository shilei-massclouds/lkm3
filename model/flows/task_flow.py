"""Task Flow"""

from framework.engine import System, visibility
from framework.sync import TASKPRIVATE_CV


@visibility(TASKPRIVATE_CV)
class TaskFlow(System):
    """Synchronous task actions receive their environment through each signal."""
