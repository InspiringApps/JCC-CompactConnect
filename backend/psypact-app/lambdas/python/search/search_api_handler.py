def search_api_handler(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.search import search_api_handler as shared

    return shared(*args, **kwargs)
