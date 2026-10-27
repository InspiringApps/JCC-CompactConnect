def public_get_provider(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.public_lookup import public_get_provider as shared

    return shared(*args, **kwargs)
