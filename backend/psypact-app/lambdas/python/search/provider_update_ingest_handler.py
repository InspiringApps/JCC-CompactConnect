def provider_update_ingest_handler(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.provider_update_ingest import provider_update_ingest_handler as shared

    return shared(*args, **kwargs)
