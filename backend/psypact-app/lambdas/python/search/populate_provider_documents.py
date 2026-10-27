def populate_provider_documents(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.populate_provider_documents import populate_provider_documents as shared

    return shared(*args, **kwargs)
