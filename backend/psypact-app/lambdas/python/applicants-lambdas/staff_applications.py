def staff_applications(*args, **kwargs):
    from cc_common.runtime import install

    install()
    from handlers.staff_applications import staff_applications as _staff_applications

    return _staff_applications(*args, **kwargs)
