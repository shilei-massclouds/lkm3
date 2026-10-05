# Kernel model

The model runs synchronous actions and nested drivers on independent task stacks.
Each task owns its contention vector, log depth and signal queue stack. A greenlet
saves the stack when a task calls `Scheduler.schedule`. Task 0 starts directly
on the caller's stack, before any scheduler exists. Its `sched_init` action
initializes the scheduler before enabling IRQs. It then creates and enables
task 1 (`kernel_init`) and task 2 (`kthreadd`) before scheduling for the first time.

The scheduler owns an internal greenlet, activated only by `schedule` calls.
Its queue holds ordinary tasks waiting to run; a yielding task joins the tail,
a blocked task leaves the queue until enabled again, and a finished task is
removed. Task 0 is the separate idle fallback, selected when no ordinary task
is ready. There is no public `Scheduler.run` entry point.

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

Create a bootstrap `TaskLocalEnv()` for synchronous setup. Pass the environment
explicitly to `System.drive(env, target, action, **kwargs)` and
`System.drive_all(env, targets, action, **kwargs)`. Task actions pass `sig.env`
to nested drivers and use `sig.env.cv` for synchronization primitives.

The boot task starts with contention `(0, 0, 0, 0)` and schedules explicitly
with preemption disabled. After resuming it enters an infinite idle loop,
which repeatedly calls `schedule`. Hardware idle waiting and IRQ events are
not yet modeled. Task 2 blocks while waiting for kernel-thread requests.

For now task 1's `boot_userapp` raises `DerivationStopped`, an `AssertionError`
subclass marking the temporary end of derivation. The exception unwinds the
other task stacks and the internal scheduler greenlet. `main` reports this
specific boundary as a successful stop; unrelated errors still propagate.
The default run stops before task 0 enters idle and before task 2 executes.
The boot and initialization vectors at this boundary are `(1, 0, 0, 0)` and
`(1, 1, 0, 0)`. An empty ordinary run queue alone never terminates the model.
