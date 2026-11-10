"""Provider id derived from an email address.

Migration and signup both use this so the same address always selects the same provider.
"""

import uuid

# Stable namespace so the same email always produces the same provider id.
EMAIL_PROVIDER_NAMESPACE = uuid.UUID('a3c1e7b2-4d58-4f0a-9c6e-2b7d1a0e5f34')


def provider_id_for_email(email: str) -> str:
    """UUID string from the stripped, lower-cased email."""
    return str(uuid.uuid5(EMAIL_PROVIDER_NAMESPACE, email.strip().lower()))
