def expiry_deactivation(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.expiry_deactivation import handler as _handler

    return _handler(*args, **kwargs)
