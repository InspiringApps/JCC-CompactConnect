def handle_data_events(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.data_events import handle_data_events as shared

    return shared(*args, **kwargs)
