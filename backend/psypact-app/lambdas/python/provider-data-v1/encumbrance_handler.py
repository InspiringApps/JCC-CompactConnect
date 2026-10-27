def encumbrance_handler(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.encumbrance import encumbrance_handler as shared

    return shared(*args, **kwargs)
