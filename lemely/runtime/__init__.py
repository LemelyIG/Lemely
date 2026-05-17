"""Cross-cutting runtime infrastructure: config, logging, errors.

Submodules are intentionally not re-exported here to avoid shadowing
stdlib names (notably ``logging``). Import directly:

    from lemely.runtime.logging import configure_logging
    from lemely.runtime.errors import LemelyError
    from lemely.runtime.config import load_settings
"""
