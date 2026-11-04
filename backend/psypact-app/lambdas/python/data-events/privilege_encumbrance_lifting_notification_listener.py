def privilege_encumbrance_lifting_notification_listener(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.encumbrance_events import privilege_encumbrance_lifting_notification_listener as shared

    return shared(*args, **kwargs)
