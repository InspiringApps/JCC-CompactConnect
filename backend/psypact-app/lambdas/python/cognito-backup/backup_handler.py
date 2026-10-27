def backup_handler(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.cognito_backup import backup_handler as shared

    return shared(*args, **kwargs)
