# Copied method bodies from backend/compact-connect/lambdas/python/common/cc_common/data_model/compact_configuration_client.py

from common_lambdas.config import logger
from common_lambdas.exceptions import CCNotFoundException


class JccCompactConfigurationClientMixin:
    def set_compact_authorize_net_public_values(self, compact: str, api_login_id: str, public_client_key: str) -> None:
        """
        Set the payment processor public fields (apiLoginId and publicClientKey) for a compact's configuration.
        This is used to store the public fields needed for the frontend Accept UI integration.

        :param compact: The compact abbreviation
        :param api_login_id: The API login ID from authorize.net
        :param public_client_key: The public client key from authorize.net
        """
        logger.info('Verifying that compact configuration exists', compact=compact)
        pk = f'{compact}#CONFIGURATION'
        sk = f'{compact}#CONFIGURATION'

        response = self.config.compact_configuration_table.get_item(Key={'pk': pk, 'sk': sk})

        item = response.get('Item')
        if not item:
            raise CCNotFoundException(f'No configuration found for compact "{compact}"')

        logger.info('Setting authorize.net public values for compact', compact=compact)

        # Use UPDATE with SET to add/update the paymentProcessorPublicFields
        self.config.compact_configuration_table.update_item(
            Key={'pk': pk, 'sk': sk},
            UpdateExpression='SET paymentProcessorPublicFields = :ppf',
            ExpressionAttributeValues={':ppf': {'apiLoginId': api_login_id, 'publicClientKey': public_client_key}},
        )

