def post_payment_processor_credentials(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.credentials import post_payment_processor_credentials as shared

    return shared(*args, **kwargs)
