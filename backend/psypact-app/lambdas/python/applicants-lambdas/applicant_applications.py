def applicant_applications(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.applicant_applications import applicant_applications as _applicant_applications

    return _applicant_applications(*args, **kwargs)
