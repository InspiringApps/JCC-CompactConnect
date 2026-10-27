def attestations(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.attestations import attestations as shared

    return shared(*args, **kwargs)
