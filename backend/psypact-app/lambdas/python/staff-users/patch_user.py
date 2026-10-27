def patch_user(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.users import patch_user as shared

    return shared(*args, **kwargs)
