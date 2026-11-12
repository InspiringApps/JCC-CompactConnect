def execution_status_reconciler(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.execution_status_reconciler import handler as _handler

    return _handler(*args, **kwargs)
