def check_feature_flag(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.check_feature_flag import check_feature_flag as shared

    return shared(*args, **kwargs)
