def get_one_user(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.users import get_one_user as shared

    return shared(*args, **kwargs)
