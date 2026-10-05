"""Context for Global vars"""

from dataclasses import dataclass, field

from drivers.console import ConsoleList
from drivers.earlycon import EarlyCon, EarlyConDrvTable, EarlyConParam
from drivers.earlycon_riscv_sbi import EarlyConRiscvSBI
from flows.boot_init_flow import BootInitFlow
from flows.kernel_init_flow import KernelInitFlow
from flows.kthreadd_flow import KthreaddFlow
from framework.scheduler import Scheduler
from framework.sync import ContentionVector
from kernel.io import Io, PrintkRingBuffer
from kernel.params import CmdLine, ParamTable
from kernel.task import KernelInitTask, Task
from systems.computer import Computer
from systems.kernel import Kernel


@dataclass
class GlobalVars:
    computer: Computer = field(default_factory=Computer)
    kernel: Kernel = field(default_factory=Kernel)
    earlycon_param: EarlyConParam = field(default_factory=EarlyConParam)
    earlycon_driver_table: EarlyConDrvTable = field(default_factory=EarlyConDrvTable)
    early_console_dev: EarlyCon = field(default_factory=EarlyCon)
    earlycon_riscv_sbi: EarlyConRiscvSBI = field(default_factory=EarlyConRiscvSBI)
    boot_command_line: CmdLine = field(default_factory=CmdLine)
    kernel_param_table: ParamTable = field(default_factory=ParamTable)
    boot_init_flow: BootInitFlow = field(default_factory=BootInitFlow)
    kernel_init_flow: KernelInitFlow = field(default_factory=KernelInitFlow)
    kthreadd_flow: KthreaddFlow = field(default_factory=KthreaddFlow)
    scheduler: Scheduler | None = field(default=None, init=False)
    boot_init_task: Task = field(init=False)
    kernel_init_task: KernelInitTask | None = field(default=None, init=False)
    kthreadd_task: Task | None = field(default=None, init=False)
    console_list: ConsoleList = field(default_factory=ConsoleList)
    io: Io = field(default_factory=Io)
    prb: PrintkRingBuffer = field(default_factory=PrintkRingBuffer)

    def __post_init__(self):
        self.scheduler = None
        self.kernel_init_task = None
        self.kthreadd_task = None
        self.boot_init_task = Task(
            "boot_init",
            self.boot_init_flow,
            "arch_boot",
            ContentionVector.zeros(),
            pid=0,
        )

    def reset(self):
        self.__init__()


gv = GlobalVars()
