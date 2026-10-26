def upload_compact_configuration(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.compact_config_uploader import on_event as shared

    return shared(*args, **kwargs)
