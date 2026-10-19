"""Module registry: every task type has exactly one owner module (invariant 2)."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from app.os.compiler import CONFIRM_TYPE
from app.os.kernel import Outcome
from app.os.kernel.kernel import NOTICE_TYPE
from app.os.playbooks import Playbook


@dataclass(frozen=True)
class TaskContext:
    task_id: int
    attempt: int
    task_type: str
    plan_id: int
    programme_ref: str | None
    payload: dict


@dataclass(frozen=True)
class Module:
    """`handler` None: the module owns student tasks, which are never executed by a worker."""

    name: str
    owns: frozenset[str]
    handler: Callable[[TaskContext], Outcome] | None


class Registry:
    def __init__(self) -> None:
        self._owner: dict[str, Module] = {}
        self._modules: dict[str, Module] = {}

    def register(self, module: Module) -> None:
        for task_type in module.owns:
            if task_type in self._owner:
                raise ValueError(f"task_type '{task_type}' already owned by '{self._owner[task_type].name}'")
        self._modules[module.name] = module
        for task_type in module.owns:
            self._owner[task_type] = module

    def replace(self, module: Module) -> None:
        """Swaps the handler of an already registered module (same name, same task types)."""
        old = self._modules[module.name]
        if old.owns != module.owns:
            raise ValueError(f"module '{module.name}' must keep its task types")
        self._modules[module.name] = module
        for task_type in module.owns:
            self._owner[task_type] = module

    def owner(self, task_type: str) -> Module:
        return self._owner[task_type]

    def modules(self) -> list[Module]:
        return list(self._modules.values())

    def types_of(self, module_names: Iterable[str]) -> frozenset[str]:
        names = set(module_names)
        return frozenset(t for t, m in self._owner.items() if m.name in names)

    def validate(self, playbooks: Iterable[Playbook]) -> None:
        needed = {CONFIRM_TYPE, NOTICE_TYPE}
        for book in playbooks:
            needed |= {t.task_type for t in book.tasks}
        missing = sorted(needed - set(self._owner))
        if missing:
            raise ValueError(f"task types without an owner module: {missing}")
