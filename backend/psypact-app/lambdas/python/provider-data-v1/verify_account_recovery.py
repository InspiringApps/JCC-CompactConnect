def verify_account_recovery(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.account_recovery import verify_account_recovery as shared

    return shared(*args, **kwargs)
