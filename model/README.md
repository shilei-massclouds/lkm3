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

Scheduling disables local IRQs before entering the CPU-scoped `switch` action,
which records a `BusyWaitPreemption` lock protecting the run queue. The incoming
task runs `finish_switch` to release its recorded lock and enable IRQs; a new
task first establishes the corresponding protection through `schedule_tail`.
Suspended tasks retain their own CV records until they resume. An exiting task
returns itself to the incoming greenlet so that `finish_switch` can also balance
its final protection record. These records describe each task's derivation
state and do not represent concurrent runtime lock owners.

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

Contention declarations use `@visibility(...)` on classes or methods. Method
declarations take precedence over the nearest class declaration. `visibility`
falls back to a full-scope vector (all one), while every target uses the fixed
exclusive safety boundary `EXCLUSIVE_CV` (all zero). `EXCLUSIVE_CV` and
`FREE_CV` name environment presets; `TRANSPARENT_CV` and `FULLSCOPE_CV` name
the corresponding visibility values, even though the component values overlap.
`TASKPRIVATE_CV` is also all zero, but denotes a target private to its owning
task rather than a transparent convenience wrapper. Other visibility presets
select a context scope: `CPUSCOPE_CV` is `(1, 1, 0, 0)` for per-CPU
visibility, `TASKSCOPE_CV` is `(0, 1, 0, 1)` for task-context visibility, and
`IRQSCOPE_CV` is `(1, 0, 1, 0)` for interrupt-context visibility.

## Contention-vector model

`framework/contention.py` defines contention vectors and the environment,
boundary and visibility presets. `framework/sync_primitives.py` defines
synchronization operations and their scoped guards, importing the vector type
from `contention.py`. Callers import vectors and operations from their respective
modules.

The four components of a `ContentionVector` are interpreted from the current
task's point of view while it accesses a target system. The same vector shape
has three distinct roles:

- `env.cv` describes the current task's synchronization state in relation to
  each other domain. It is passed through the current task's nested call stack,
  and synchronization primitives adjust the relevant component to express the
  concurrency state established by that primitive. A lower value does not by
  itself imply that an operation blocks or excludes its competitors.
- The target's `visibility` describes whether the target can be seen by each
  other domain. An invisible domain cannot compete with that target. Visibility
  is per-domain, so a target can be visible to some domains and invisible to
  others. `TRANSPARENT_CV` (all zero) marks a convenience wrapper whose nested
  actions carry the actual safety requirements; `TASKPRIVATE_CV` (all zero)
  marks a target private to its owning task; `FULLSCOPE_CV` (all one) marks a
  target visible to every domain.
- The target's safety boundary is the fixed `EXCLUSIVE_CV`, meaning exclusive
  access in every domain.

Dispatch first combines the environment and the target's visibility with a
minimum, then checks the result against the fixed target boundary:

```text
effective_cv[d] = min(env.cv[d], target.visibility[d])
assert effective_cv <= EXCLUSIVE_CV
```

The check is component-wise across local IRQ, local tasks, remote IRQ and
remote tasks. A zero visibility component masks contention in that domain; a
one component preserves the environment's constraint.

Each environment vector also owns four protection stacks, accessed through
`cv.stacks[domain]`. Synchronization primitives decrement a component and push
the object they protect; release pops that same object in stack order and
increments the component. `None` denotes global protection. Initially absent
competitors are also represented by `None`; enabling IRQs, local multitasking
or remote CPUs removes the corresponding global protection.

For every visible domain, dispatch checks both the count and the stack. The
count must satisfy the fixed exclusive boundary, and the stack must contain
either `None`, a matching class, or the exact target instance, compared by
identity. An explicit `protected_by(Class)` declaration extends the class
match for that action. Matching references can appear anywhere in the stack.
Invisible domains do not need a matching reference. Transparent routing actions
therefore remain callable before their nested actions acquire the appropriate
target protection.

Locks and their guards take an explicit protected target, for example
`GuardBusyWaitIrqSavePreemption(cv, task)` and
`GuardBusyWaitPreemption(cv, runq)`. Their IRQ and preemption components push
`None`, while their busy-wait components push the target. Yielding locks push
their target in each domain they protect. An explicit `None` target represents
global protection; console flushing currently uses this abstraction for its
shared critical region.

`VersionedRead` records its target in all four protection stacks while a
versioned read is active. The model captures the resulting concurrent state;
the concrete publication and validation protocol remains outside this
abstraction.

Copying a vector copies the four lists independently and retains the protected
object references. Numerical comparison and `min()` do not combine protection
stacks; invariant checks always consult the original environment stacks.
IRQ save/restore uses `IrqFlags`, which saves both the level and the IRQ stack
so that nested guards restore the surrounding protection without changing
other domains. These stacks describe the current task's derivation path;
the engine does not simulate concurrent lock owners.

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
The boot task enables remote CPU contention before its first schedule.
The boot and initialization vectors at this boundary are `(1, 0, 1, 1)` and
`(1, 1, 1, 1)`. An empty ordinary run queue alone never terminates the model.
