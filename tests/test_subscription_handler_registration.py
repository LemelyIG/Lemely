"""The subscription paid handlers register without any router being imported (DV-10).

The reconcile sweeper reaches ``BillingService`` through ``lemely.web.billing_jobs`` alone. If the
subscription handlers were registered only when a router imported ``subscription_repo``, a
``subscription_first`` payment reconciled in a process that never imported that router would raise
"no paid handler" on every pass. A fresh interpreter proves the import graph, which an in-process
test cannot: pytest has long since imported everything.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

_PROBE = (
    "import lemely.web.billing_jobs; "
    "from lemely.db.billing_repo import paid_handler_for; "
    "from lemely.db.models.billing import PaymentPurpose as P; "
    "assert paid_handler_for(P.subscription_first), 'subscription_first'; "
    "assert paid_handler_for(P.subscription_renewal), 'subscription_renewal'"
)


def test_billing_jobs_alone_registers_both_subscription_handlers() -> None:
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    # A fixed argv built from this interpreter and a constant script: nothing untrusted.
    subprocess.run(  # noqa: S603
        [sys.executable, "-c", _PROBE], env=env, cwd=REPO, check=True, timeout=120
    )


def test_billing_jobs_imports_the_subscription_repo_itself() -> None:
    """The subprocess above passes through ``lemely.web``'s package import, which pulls in the
    admin modules (and so ``subscription_repo``) by accident. This pins the intended edge: the
    sweeper's own module names the registration import, so no refactor of those routers can
    silently drop it.
    """
    tree = ast.parse((REPO / "lemely" / "web" / "billing_jobs.py").read_text())
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "lemely.db.subscription_repo" in imported
