def get_me(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.me import get_me as shared

    return shared(*args, **kwargs)
