def investigation_handler(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.investigation import investigation_handler as shared

    return shared(*args, **kwargs)
