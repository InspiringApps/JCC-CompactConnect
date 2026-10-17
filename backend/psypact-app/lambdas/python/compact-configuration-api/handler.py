def compact_configuration_api_handler(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.compact_configuration import compact_configuration_api_handler as shared

    return shared(*args, **kwargs)
