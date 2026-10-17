"""Start a ``spawn`` child without re-running the parent's ``__main__`` (#260).

CPython's ``multiprocessing.spawn`` re-runs the parent's main module in the
child before it unpickles the target (``_fixup_main_from_path``,
``_fixup_main_from_name``): a path-run script, or a ``-m`` module not named
``__main__``. That happens before the child sets any limit of its own, so a
script that imported ``lemely.web`` at its top level left a scan worker's
child at ~827 MB ``VmData``, over both its limits, and every scan failed
(final review R1, Important 1). The equivalence parse worker had the same
start, and a script calling ``parse_expr_safe`` at import time needed an
``if __name__ == "__main__":`` guard.

:func:`start_without_parent_main` is the one start both child processes use:
the scan workers (:class:`lemely.runtime.sandbox.ChildWorker`) and the parse
worker (``lemely.core.equivalence_worker._ParseWorker``). Nothing either
child is given lives in ``__main__``: the scan workers name their targets by
dotted path, and the parse worker's entry point is a module-level function of
``lemely.core.equivalence_worker`` (``_parse_worker_main``).
"""

from __future__ import annotations

import importlib.machinery
import os
import sys
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multiprocessing.process import BaseProcess

#: Held while ``__main__.__spec__`` is swapped for a child's start
#: (:func:`start_without_parent_main`): two workers starting at once would
#: otherwise save each other's stand-in and leave it in place. Also held
#: across an ``os.fork`` (the ``register_at_fork`` call at the end of this
#: module), so a forked process never inherits the stand-in or a held lock.
#: ``spawn`` starts its child with ``fork_exec``, which runs no fork hooks,
#: so a start under the lock cannot deadlock on it.
_MAIN_SWAP_LOCK = threading.Lock()

#: What ``spawn`` is shown as ``__main__``'s spec while a child starts.
#: ``multiprocessing.spawn`` leaves a main module named ``"__main__"`` or
#: ending in ``".__main__"`` alone. ``python -m lemely.web`` (the container)
#: already has such a name.
_UNRUN_MAIN_SPEC = importlib.machinery.ModuleSpec("__main__", None)


def start_without_parent_main(process: BaseProcess) -> None:
    """``process.start()``, with the child told to leave its ``__main__`` alone.

    ``spawn`` reads ``sys.modules["__main__"].__spec__`` (and, when that is
    ``None``, ``__file__``) inside ``start()`` to decide what the child
    re-runs before it unpickles its target. For the start the spec is
    :data:`_UNRUN_MAIN_SPEC`, so the child runs only its target and the
    modules that target imports. The parent's own spec (``None`` for a
    path-run script) is put back as soon as ``start()`` returns or raises,
    under :data:`_MAIN_SWAP_LOCK`.
    """
    main = sys.modules.get("__main__")
    if main is None:  # an embedding with no main module: nothing to re-run
        process.start()
        return
    with _MAIN_SWAP_LOCK:
        had_spec = "__spec__" in vars(main)
        saved = main.__spec__ if had_spec else None
        main.__spec__ = _UNRUN_MAIN_SPEC
        try:
            process.start()
        finally:
            if had_spec:
                main.__spec__ = saved
            else:
                del main.__spec__


if hasattr(os, "register_at_fork"):
    os.register_at_fork(
        before=_MAIN_SWAP_LOCK.acquire,
        after_in_parent=_MAIN_SWAP_LOCK.release,
        after_in_child=_MAIN_SWAP_LOCK.release,
    )
