def manage_opensearch_indices(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.manage_opensearch_indices import on_event as shared

    return shared(*args, **kwargs)
