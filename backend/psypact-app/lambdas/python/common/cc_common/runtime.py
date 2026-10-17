"""Install PSYPACT config before shared handlers bind it."""

_installed = False


def install() -> None:
    """Replace the shared config singleton with the PSYPACT config."""
    global _installed
    if _installed:
        return

    import common_lambdas.config as config_module

    from cc_common.psypact_config import PsypactConfig

    if not isinstance(config_module.config, PsypactConfig):
        config_module.config = PsypactConfig()

    _installed = True
