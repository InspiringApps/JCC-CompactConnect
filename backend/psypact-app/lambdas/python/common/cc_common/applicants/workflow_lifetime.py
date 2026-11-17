"""How long one application generation may run before its expiry schedule fires."""

import os
from datetime import timedelta

_OFFICIAL_ENVIRONMENTS = frozenset({'test', 'beta', 'prod'})
_DEFAULT_LIFETIME = timedelta(days=365)


def workflow_lifetime() -> timedelta:
    """Return one year, or a sandbox-only shorter override.

    ``APPLICATION_WORKFLOW_LIFETIME_SECONDS`` is ignored for the official test,
    beta, and prod environments. A sandbox deploy may set it so a smoke test can
    reach the expiry schedule without waiting a year.
    """
    raw = os.environ.get('APPLICATION_WORKFLOW_LIFETIME_SECONDS')
    environment = os.environ.get('ENVIRONMENT_NAME', '')
    if not raw or environment in _OFFICIAL_ENVIRONMENTS:
        return _DEFAULT_LIFETIME
    return timedelta(seconds=int(raw))
