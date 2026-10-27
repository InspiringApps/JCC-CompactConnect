def reinvite_user(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.users import reinvite_user as shared

    return shared(*args, **kwargs)
