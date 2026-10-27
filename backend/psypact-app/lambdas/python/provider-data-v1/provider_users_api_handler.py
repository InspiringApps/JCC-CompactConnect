def provider_users_api_handler(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.provider_users import provider_users_api_handler as shared

    return shared(*args, **kwargs)
