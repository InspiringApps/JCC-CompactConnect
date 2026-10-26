def license_investigation_closed_notification_listener(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.investigation_events import license_investigation_closed_notification_listener as shared

    return shared(*args, **kwargs)
