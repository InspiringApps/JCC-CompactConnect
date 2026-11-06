def enter_state(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.enter_state import enter_state as _enter_state

    return _enter_state(*args, **kwargs)
