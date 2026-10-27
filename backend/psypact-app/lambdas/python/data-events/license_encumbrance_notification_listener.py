def license_encumbrance_notification_listener(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.encumbrance_events import license_encumbrance_notification_listener as shared

    return shared(*args, **kwargs)
