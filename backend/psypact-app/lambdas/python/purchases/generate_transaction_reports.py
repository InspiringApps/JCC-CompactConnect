def generate_transaction_reports(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.transaction_reporting import generate_transaction_reports as shared

    return shared(*args, **kwargs)
