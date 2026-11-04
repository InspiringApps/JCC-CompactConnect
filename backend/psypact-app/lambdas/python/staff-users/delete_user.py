def delete_user(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.users import delete_user as shared

    return shared(*args, **kwargs)
