def patch_me(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.me import patch_me as shared

    return shared(*args, **kwargs)
