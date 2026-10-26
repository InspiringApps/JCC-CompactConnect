def get_users(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.users import get_users as shared

    return shared(*args, **kwargs)
