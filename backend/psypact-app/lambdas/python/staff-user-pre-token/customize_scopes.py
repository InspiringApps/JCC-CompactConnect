def customize_scopes(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from main import customize_scopes as shared

    return shared(*args, **kwargs)
