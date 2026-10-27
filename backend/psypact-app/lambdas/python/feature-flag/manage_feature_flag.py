def manage_feature_flag(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.manage_feature_flag import on_event as shared

    return shared(*args, **kwargs)
