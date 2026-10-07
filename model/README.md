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
make clean
```

Synchronous entrypoints receive an explicit `TaskLocalEnv`. `main.py` intentionally
creates one fresh bootstrap environment for `Kernel.setup` and another for
`Kernel.boot`; these are independent entrypoints. Task actions pass `sig.env`
to nested drivers and use `sig.env.cv` for synchronization primitives.
Each `Task` owns a distinct `TaskFlow` instance. Tasks may use the same flow
class, but sharing one flow instance is rejected.

Contention declarations use `@requires_cv(...)` and `@visibility(...)` on
classes or methods. Method declarations take precedence over the nearest class
declaration. `requires_cv` falls back to an exclusive vector (all zero), while
`visibility` falls back to a full-scope vector (all one). Neither declaration
is an instance field on `System`. `EXCLUSIVE_CV` and `FREE_CV` name the
environment and requirement defaults; `TRANSPARENT_CV` and `FULLSCOPE_CV` name
the corresponding visibility values, even though the component values overlap.
`TASKPRIVATE_CV` is also all zero, but denotes a target private to its owning
task rather than a transparent convenience wrapper. Other visibility presets
select a context scope: `CPUSCOPE_CV` is `(1, 1, 0, 0)` for per-CPU
visibility, `TASKSCOPE_CV` is `(0, 1, 0, 1)` for task-context visibility, and
`IRQSCOPE_CV` is `(1, 0, 1, 0)` for interrupt-context visibility.

`requires_cv` is deprecated and retained only as a migration compatibility
interface. Do not add new uses. Each call to `requires_cv(...)` emits a
`DeprecationWarning` at the declaration site; existing declarations still
keep their current contention-check behavior. Use `SyncPrimitive` to adjust
environment contention and `visibility` to express target scope instead.
Existing declarations will be migrated individually, without mechanically
inverting their requirement vectors into visibility.

## Contention-vector model

The four components of a `ContentionVector` are interpreted from the current
task's point of view while it accesses a target system. The same vector shape
has three distinct roles:

- `env.cv` describes whether each other domain can compete with the current
  access to the target. It is passed through the current task's nested call
  stack, and synchronization primitives adjust the relevant component.
- The target's `visibility` describes whether the target can be seen by each
  other domain. An invisible domain cannot compete with that target. Visibility
  is per-domain, so a target can be visible to some domains and invisible to
  others. `TRANSPARENT_CV` (all zero) marks a convenience wrapper whose nested
  actions carry the actual safety requirements; `TASKPRIVATE_CV` (all zero)
  marks a target private to its owning task; `FULLSCOPE_CV` (all one) marks a
  target visible to every domain.
- The target's legacy `requires_cv` is its safe contention boundary during
  migration. It defaults to all zero, meaning exclusive access, and a
  declaration can permit contention in selected domains.

During migration, dispatch first combines the environment and the target's
resolved visibility with a minimum, then checks the result against the target's
resolved boundary:

```text
effective_cv[d] = min(env.cv[d], target.visibility[d])
assert effective_cv <= target.requires_cv
```

The check is component-wise across local IRQ, local tasks, remote IRQ and
remote tasks. A zero visibility component masks contention in that domain; a
one component preserves the environment's constraint.

After all legacy declarations have been migrated, `requires_cv` will be removed
and every target will use the fixed exclusive safety boundary `EXCLUSIVE_CV`:

```text
effective_cv[d] = min(env.cv[d], target.visibility[d])
assert effective_cv <= EXCLUSIVE_CV
```

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
