def public_search_api_handler(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.public_search import public_search_api_handler as shared

    return shared(*args, **kwargs)
