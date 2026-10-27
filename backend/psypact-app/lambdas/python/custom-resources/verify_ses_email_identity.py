def verify_ses_email_identity(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.ses_email_identity_verification_handler import on_event as shared

    return shared(*args, **kwargs)
