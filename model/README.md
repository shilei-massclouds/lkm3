# Kernel model

The model runs synchronous actions and nested drivers on independent task stacks.
Each task owns its contention vector, log depth and signal queue stack. A greenlet
saves the stack when a task calls `Scheduler.schedule`. Task 0 starts directly
on the caller's stack, before any scheduler exists. Its `sched_init` action
initializes the scheduler before enabling IRQs. It then creates and enables
task 1 (`kernel_init`) and task 2 (`kthreadd`) before scheduling for the first time.

The scheduler executes on the calling task's stack. Its queue holds ordinary
tasks waiting to run; a yielding task joins the tail and a blocked task leaves
the queue until enabled again. `schedule` selects the next task and switches
directly to its greenlet. When a task finishes, it selects the next task and
returns directly to that greenlet. Task 0 is the separate idle fallback,
selected when no ordinary task is ready. The scheduler has no greenlet or
dispatch loop of its own.

Use Python 3.14 and `greenlet>=3.3,<4`. Install the Python dependency with:

```sh
python3 -m pip install -r requirements.txt
```

On Ubuntu, the system package can be installed with:

```sh
sudo apt update
sudo apt install python3-greenlet
python3 -c 'import greenlet; print(greenlet.__version__)'
```

Check that the system package meets the version requirement. Development checks
also require Ruff, Pyright and pytest.

```sh
make test
make test DEBUG=y
make run DEBUG=y
```

Synchronous entrypoints receive an explicit `TaskLocalEnv`. `main.py` intentionally
creates one fresh bootstrap environment for `Kernel.setup` and another for
`Kernel.boot`; these are independent entrypoints. Task actions pass `sig.env`
to nested drivers and use `sig.env.cv` for synchronization primitives.

The boot task starts with contention `(0, 0, 0, 0)` and schedules explicitly
with preemption disabled. After resuming it performs three idle iterations,
each calling `schedule`. Hardware idle waiting and IRQ events are not yet
modeled. Task 2 blocks while waiting for kernel-thread requests.

For now task 1's `boot_userapp` calls `terminate`, which prints the temporary
user application boundary and exits the process with status 0. This is the
normal end of the current derivation; it is distinct from assertion failures
for invalid states and contention violations. There are no custom exception
types, recovery or peer cancellation. Active drivers still restore their queue
stacks and depth in `finally`. Start a fresh model with `gv.reset()` for another
derivation.

The default run stops before task 0 enters idle and before task 2 executes;
`make run` returns status 0 at the termination boundary.
The boot and initialization vectors at this boundary are `(1, 0, 0, 0)` and
`(1, 1, 0, 0)`. An empty ordinary run queue alone never terminates the model.
