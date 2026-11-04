def get_provider(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.providers import get_provider as shared

    return shared(*args, **kwargs)
