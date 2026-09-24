import common_lambdas.config as config_module
from common_lambdas.psypact_config import PsypactConfig

# Replace the Cosmetology singleton so copied handlers that import
# `from common_lambdas.config import config` receive PSYPACT clients/records.
config_module.config = PsypactConfig()
