def home_jurisdiction_change_notification_listener(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.home_jurisdiction_events import home_jurisdiction_change_notification_listener as shared

    return shared(*args, **kwargs)
