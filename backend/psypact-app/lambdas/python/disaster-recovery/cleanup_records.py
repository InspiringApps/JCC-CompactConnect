def cleanup_records(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.cleanup_records import cleanup_records as shared

    return shared(*args, **kwargs)
