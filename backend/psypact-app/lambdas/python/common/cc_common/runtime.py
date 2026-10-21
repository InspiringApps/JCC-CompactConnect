"""Install PSYPACT config and response schemas before shared handlers bind them."""

_installed = False


def install() -> None:
    """Replace the shared config singleton and privilege response schemas."""
    global _installed
    if _installed:
        return

    import common_lambdas.config as config_module

    from cc_common.psypact_config import PsypactConfig

    if not isinstance(config_module.config, PsypactConfig):
        config_module.config = PsypactConfig()

    from cc_common.data_model.psypact_authorization_schema import install_psypact_authorization_schema
    from cc_common.data_model.psypact_privilege_schema import install_psypact_privilege_schemas

    install_psypact_authorization_schema()
    install_psypact_privilege_schemas()
    _installed = True
