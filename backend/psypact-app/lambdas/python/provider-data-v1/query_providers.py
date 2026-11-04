def query_providers(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.providers import query_providers as shared

    return shared(*args, **kwargs)
