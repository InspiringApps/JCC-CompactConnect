def copy_records(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.copy_records import copy_records as shared

    return shared(*args, **kwargs)
