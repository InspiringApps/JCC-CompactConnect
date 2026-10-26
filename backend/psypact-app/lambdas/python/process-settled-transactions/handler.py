def process_settled_transactions(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.transaction_history import process_settled_transactions as shared

    return shared(*args, **kwargs)
