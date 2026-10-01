# Copied method bodies from backend/compact-connect/lambdas/python/common/cc_common/data_model/data_client.py
# ruff: noqa: C901, PLR0915, PLR0912, ARG002
from datetime import datetime

from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

from common_lambdas.config import (
    config,
    logger,
)
from common_lambdas.data_model.provider_record_util import (
    ProviderRecordUtility,
    ProviderUserRecords,
)
from common_lambdas.data_model.schema.common import (
    CompactEligibilityStatus,
    HomeJurisdictionChangeStatusEnum,
    LicenseEncumberedStatusEnum,
    PrivilegeEncumberedStatusEnum,
    UpdateCategory,
)
from common_lambdas.data_model.schema.license import LicenseData
from common_lambdas.data_model.schema.military_affiliation import MilitaryAffiliationData
from common_lambdas.data_model.schema.military_affiliation.common import (
    MilitaryAffiliationStatus,
    MilitaryAffiliationType,
)
from common_lambdas.data_model.schema.military_affiliation.record import MilitaryAffiliationRecordSchema
from common_lambdas.data_model.schema.privilege.jcc_data import (
    PrivilegeData,
    PrivilegeUpdateData,
)
from common_lambdas.data_model.schema.provider.jcc_provider import (
    ProviderData,
    ProviderUpdateData,
)
from common_lambdas.exceptions import (
    CCAwsServiceException,
    CCInternalException,
    CCNotFoundException,
)
from common_lambdas.psypact_records import ProviderRecordType
from common_lambdas.utils import logger_inject_kwargs

MAX_DYNAMODB_TRANSACTION_ITEMS = 100


class JccDataClientMixin:
    def _get_all_military_affiliation_records_for_provider(self, compact: str, provider_id: str):
        military_affiliation_records = self.config.provider_table.query(
            KeyConditionExpression=Key('pk').eq(f'{compact}#PROVIDER#{provider_id}')
            & Key('sk').begins_with(
                f'{compact}#PROVIDER#military-affiliation#',
            ),
        ).get('Items', [])

        return [MilitaryAffiliationData.from_database_record(record) for record in military_affiliation_records]

    @logger_inject_kwargs(logger, 'compact', 'provider_id', 'affiliation_type')
    def create_military_affiliation(
        self,
        compact: str,
        provider_id: str,
        affiliation_type: MilitaryAffiliationType,
        file_names: list[str],
        document_keys: list[str],
    ):
        """
        Create a new military affiliation record for a provider in the database.

        If there are any previous active military affiliations for this provider, they will be set to inactive.

        :param compact: The compact name
        :param provider_id: The provider id
        :param affiliation_type: The type of military affiliation
        :param file_names: The list of file names for the documents
        :param document_keys: The list of s3 document keys for the documents
        :return: The created military affiliation record
        """
        logger.info('Creating military affiliation')

        latest_military_affiliation_record = {
            'type': ProviderRecordType.MILITARY_AFFILIATION,
            'affiliationType': affiliation_type.value,
            'fileNames': file_names,
            'compact': compact,
            'providerId': provider_id,
            # we set this to initializing until the client uploads the document, which
            # will trigger another lambda to update the status to active
            'status': MilitaryAffiliationStatus.INITIALIZING.value,
            'documentKeys': document_keys,
            'dateOfUpload': config.current_standard_datetime,
        }

        schema = MilitaryAffiliationRecordSchema()
        latest_military_affiliation_record_serialized = schema.dump(latest_military_affiliation_record)

        # We need to check for any other military affiliations for this provider
        # and set them to inactive. Note these could be consolidated into a single batch call if performance
        # becomes an issue.
        self.inactivate_current_military_affiliation_records(compact, provider_id)

        with self.config.provider_table.batch_writer() as batch:
            batch.put_item(Item=latest_military_affiliation_record_serialized)

        return latest_military_affiliation_record

    @logger_inject_kwargs(logger, 'compact', 'provider_id')
    def end_military_affiliation(self, compact: str, provider_id: str) -> None:
        """
        End a provider's military affiliation by removing military status fields and deactivating all active records.

        This method:
        1. Removes 'militaryStatus' and 'militaryStatusNote' from the provider record
        2. Creates a provider update record tracking the removal of these fields
        3. Sets all INITIALIZING or ACTIVE military affiliation records to INACTIVE

        All operations are performed in a DynamoDB transaction to ensure consistency.

        :param compact: The compact name
        :param provider_id: The provider id
        :raises CCNotFoundException: If provider not found
        """
        logger.info('Ending military affiliation for provider')

        # Get provider records
        provider_user_records = self.get_provider_user_records(compact=compact, provider_id=provider_id)
        provider_record = provider_user_records.get_provider_record()

        # Capture previous state before updating
        previous_provider_state = provider_record.to_dict()

        # Get all military affiliation records that are INITIALIZING or ACTIVE
        active_military_affiliation_records = provider_user_records.get_military_affiliation_records(
            filter_condition=lambda record: (
                record.status in [MilitaryAffiliationStatus.INITIALIZING, MilitaryAffiliationStatus.ACTIVE]
            )
        )

        # Create provider update record to track the removal of military status fields
        now = config.current_standard_datetime
        removed_values = []
        if previous_provider_state.get('militaryStatus') is not None:
            removed_values.append('militaryStatus')
        if previous_provider_state.get('militaryStatusNote') is not None:
            removed_values.append('militaryStatusNote')

        update_record_data = {
            'type': ProviderRecordType.PROVIDER_UPDATE,
            'updateType': UpdateCategory.MILITARY_AFFILIATION_ENDED,
            'providerId': provider_id,
            'compact': compact,
            'previous': previous_provider_state,
            'createDate': now,
            'updatedValues': {},
        }
        if removed_values:
            update_record_data['removedValues'] = removed_values

        provider_update_record = ProviderUpdateData.create_new(update_record_data)

        # Build transaction items
        transaction_items = []

        # Update provider record to remove militaryStatus and militaryStatusNote
        provider_serialized_record = provider_record.serialize_to_database_record()
        transaction_items.append(
            {
                'Update': {
                    'TableName': self.config.provider_table_name,
                    'Key': {
                        'pk': {'S': provider_serialized_record['pk']},
                        'sk': {'S': provider_serialized_record['sk']},
                    },
                    'UpdateExpression': (
                        'SET dateOfUpdate = :dateOfUpdate, providerDateOfUpdate = :providerDateOfUpdate '
                        'REMOVE militaryStatus, militaryStatusNote'
                    ),
                    'ExpressionAttributeValues': {
                        ':dateOfUpdate': {'S': now.isoformat()},
                        ':providerDateOfUpdate': {'S': now.isoformat()},
                    },
                    'ConditionExpression': 'attribute_exists(pk)',
                }
            }
        )

        # Create provider update record
        transaction_items.append(
            {
                'Put': {
                    'TableName': self.config.provider_table_name,
                    'Item': TypeSerializer().serialize(provider_update_record.serialize_to_database_record())['M'],
                }
            }
        )

        # Update all active/initializing military affiliation records to inactive
        for record in active_military_affiliation_records:
            record.update({'status': MilitaryAffiliationStatus.INACTIVE.value})
            serialized_record = record.serialize_to_database_record()
            transaction_items.append(
                {
                    'Put': {
                        'TableName': self.config.provider_table_name,
                        'Item': TypeSerializer().serialize(serialized_record)['M'],
                    }
                }
            )

        # Execute transaction in batches if needed (DynamoDB limit is 100 items)
        batch_size = 100
        while transaction_items:
            batch = transaction_items[:batch_size]
            transaction_items = transaction_items[batch_size:]

            try:
                self.config.dynamodb_client.transact_write_items(TransactItems=batch)
                logger.info('Successfully processed military affiliation end batch', batch_size=len(batch))
            except ClientError as e:
                logger.error('Failed to process military affiliation end transaction', error=str(e))
                raise CCAwsServiceException('Failed to end military affiliation') from e

        logger.info('Successfully ended military affiliation for provider')

    def inactivate_current_military_affiliation_records(self, compact: str, provider_id: str):
        """
        Sets all military affiliation records to an inactive status for a provider in the database.

        :param compact: The compact name
        :param provider_id: The provider id
        :return: None
        """
        military_affiliation_records = self._get_all_military_affiliation_records_for_provider(compact, provider_id)
        with self.config.provider_table.batch_writer() as batch:
            for record in military_affiliation_records:
                record.update({'status': MilitaryAffiliationStatus.INACTIVE.value})
                serialized_record = record.serialize_to_database_record()
                batch.put_item(Item=serialized_record)

    @logger_inject_kwargs(logger, 'compact', 'transaction_id')
    def get_privilege_for_transaction_id(self, *, compact: str, transaction_id: str) -> PrivilegeData:
        """
        Return a privilege record for a payment transaction id using the compact transaction id GSI.

        :param compact: Compact abbreviation
        :param transaction_id: Payment processor transaction id
        :raises CCNotFoundException: When no item with type ``privilege`` exists for this transaction id
        :return: The privilege as :class:`PrivilegeData`
        """
        gsi_pk = f'COMPACT#{compact}#TX#{transaction_id}#'
        response = self.config.provider_table.query(
            IndexName=self.config.compact_transaction_id_gsi_name,
            KeyConditionExpression=Key('compactTransactionIdGSIPK').eq(gsi_pk),
        )
        items = response.get('Items', [])
        for item in items:
            if item.get('type') == 'privilege':
                return PrivilegeData.from_database_record(item)
        raise CCNotFoundException('No privilege record found for transaction id')

    def _process_jurisdiction_change_deactivation(
        self,
        compact: str,
        provider_id: str,
        top_level_provider_record: ProviderData,
        selected_jurisdiction: str,
        all_active_privileges: list[PrivilegeData],
        all_transaction_items: list[dict],
    ) -> None:
        # Get provider record update transaction items for jurisdiction with no valid license
        provider_transaction_items = self._get_provider_record_transaction_items_for_jurisdiction_with_no_known_license(
            compact=compact,
            provider_id=provider_id,
            provider_record=top_level_provider_record,
            selected_jurisdiction=selected_jurisdiction,
        )
        all_transaction_items.extend(provider_transaction_items)

        # Get privilege deactivation transaction items
        privilege_transaction_items = self._get_privilege_deactivation_transaction_items_for_jurisdiction_change(
            compact=compact, provider_id=provider_id, privileges=all_active_privileges
        )
        all_transaction_items.extend(privilege_transaction_items)

    @logger_inject_kwargs(logger, 'compact', 'provider_id', 'selected_jurisdiction')
    def update_provider_home_state_jurisdiction(
        self, *, compact: str, provider_id: str, selected_jurisdiction: str
    ) -> str | None:
        """
        Update the provider's home jurisdiction and handle their privileges according to business rules.

        The following rules are applied when updating the provider's home state jurisdiction:
        1. If the provider does not have any known license in the selected jurisdiction, all of their existing
           privileges will have their 'homeJurisdictionChangeStatus' set to 'inactive'
        3. Else if the license in the current home state is expired, the privileges are not moved over. If the license
           is later updated and the provider renews the privileges, they will be associated with the new home state.
        3. Else if the license in the current home state is encumbered, all privileges will not be moved over
           to the new jurisdiction. They stay encumbered.
        4. Else if the license in the new jurisdiction has a 'compactEligibility' status of 'ineligible', the associated
           privileges for the current license will NOT be moved over to the new jurisdiction, we will set the
           'homeJurisdictionChangeStatus' field to 'inactive'.
        5. If the license in the new home state is encumbered, unexpired privileges are moved over and all privileges
           that do not already have an encumbered status of 'encumbered' will have their encumbered status set to
           'licenseEncumbered'.
        6. If none of the above conditions are met, the provider's unexpired privileges will be moved over to the new
           jurisdiction and the expiration date will be updated to the expiration date of the license in the new
           jurisdiction. (the only exception to this is if any existing privilege is for the same jurisdiction as the
           new license, in which case it is deactivated).

        :param compact: The compact name
        :param provider_id: The provider ID
        :param selected_jurisdiction: The new home jurisdiction selected by the provider
        :return: The previous home jurisdiction (before the update), or None if there was no previous home jurisdiction
        :raises CCInternalException: If any transaction fails during the update process
        """
        logger.info('Updating provider user home jurisdiction')

        provider_user_records: ProviderUserRecords = self.get_provider_user_records(
            compact=compact, provider_id=provider_id
        )
        top_level_provider_record = provider_user_records.get_provider_record()
        home_jurisdiction_before_update = top_level_provider_record.currentHomeJurisdiction
        if home_jurisdiction_before_update.lower() == selected_jurisdiction.lower():
            logger.info(
                'New selected jurisdiction matches current home state. Returning as this is a no-op',
                compact=compact,
                current_home_jurisdiction=home_jurisdiction_before_update,
                selected_jurisdiction=selected_jurisdiction,
                provider_id=provider_id,
            )
            return home_jurisdiction_before_update

        # Get all licenses in the new home jurisdiction
        new_home_state_licenses = provider_user_records.get_license_records(
            filter_condition=lambda license_data: license_data.jurisdiction == selected_jurisdiction
        )

        # Get all privileges for the provider that were not deactivated previously
        all_active_privileges = provider_user_records.get_privilege_records(
            filter_condition=lambda privilege: (
                privilege.homeJurisdictionChangeStatus != HomeJurisdictionChangeStatusEnum.INACTIVE
            )
        )

        if not all_active_privileges:
            logger.info('No active privileges found for user. Proceeding with provider update')

        try:
            # Collect all transaction items
            all_transaction_items = []

            # Check if provider has any licenses in the new jurisdiction
            if not new_home_state_licenses:
                logger.info('No home state license found in selected jurisdiction. Deactivating all active privileges')

                self._process_jurisdiction_change_deactivation(
                    compact=compact,
                    provider_id=provider_id,
                    top_level_provider_record=top_level_provider_record,
                    selected_jurisdiction=selected_jurisdiction,
                    all_active_privileges=all_active_privileges,
                    all_transaction_items=all_transaction_items,
                )
            else:
                # Check if the selected jurisdiction is live in the compact configuration
                compact_config = self.config.compact_configuration_client.get_compact_configuration(compact)
                is_jurisdiction_live = any(
                    state['postalAbbreviation'].lower() == selected_jurisdiction.lower() and state.get('isLive', False)
                    for state in compact_config.configuredStates
                )

                if not is_jurisdiction_live:
                    logger.info(
                        'Selected jurisdiction is not live in compact configuration. '
                        'Deactivating privileges as if there were no license.',
                        selected_jurisdiction=selected_jurisdiction,
                        compact=compact,
                    )
                    self._process_jurisdiction_change_deactivation(
                        compact=compact,
                        provider_id=provider_id,
                        top_level_provider_record=top_level_provider_record,
                        selected_jurisdiction=selected_jurisdiction,
                        all_active_privileges=all_active_privileges,
                        all_transaction_items=all_transaction_items,
                    )
                else:
                    # Find the best license in the selected jurisdiction
                    best_license_in_selected_jurisdiction = (
                        provider_user_records.find_best_license_in_current_known_licenses(
                            jurisdiction=selected_jurisdiction
                        )
                    )
                    # Get provider record update transaction items for jurisdiction change with license
                    provider_transaction_items = (
                        self._get_provider_record_transaction_items_for_jurisdiction_change_with_license(
                            compact=compact,
                            provider_id=provider_id,
                            provider_records=provider_user_records,
                            new_license_record=best_license_in_selected_jurisdiction,
                            selected_jurisdiction=selected_jurisdiction,
                        )
                    )
                    all_transaction_items.extend(provider_transaction_items)

                    # Get licenses from the current home state
                    current_home_state_licenses = provider_user_records.get_license_records(
                        filter_condition=lambda license_data: (
                            license_data.jurisdiction == home_jurisdiction_before_update
                        )
                    )

                    # Get unique license types from all privileges
                    privilege_license_types = set(privilege.licenseType for privilege in all_active_privileges)

                    for license_type in privilege_license_types:
                        # Find the matching license in the current jurisdiction for this license type
                        matching_license_in_current_jurisdiction = next(
                            (
                                license_data
                                for license_data in current_home_state_licenses
                                if license_data.licenseType == license_type
                            ),
                            None,
                        )

                        if not matching_license_in_current_jurisdiction:
                            logger.info(
                                'No current home state license found for license type. '
                                'User likely previously moved to a state with no known license '
                                'and privileges were deactivated. Will not move privileges over.',
                                license_type=license_type,
                                current_home_jurisdiction=home_jurisdiction_before_update,
                                new_home_state_licenses=new_home_state_licenses,
                            )
                            continue

                        # if the current home state license is expired, then all the privileges associated
                        # with this license will also be expired, and we will not move them over
                        if (
                            matching_license_in_current_jurisdiction.dateOfExpiration
                            < self.config.expiration_resolution_date
                        ):
                            logger.info(
                                'Current home state license is expired. Not moving privileges over.',
                                license_type=license_type,
                            )
                            continue

                        if (
                            matching_license_in_current_jurisdiction.encumberedStatus
                            == LicenseEncumberedStatusEnum.ENCUMBERED
                        ):
                            logger.info(
                                'Current license is encumbered. Privileges for this license type will not be moved '
                                'over to new license.',
                                license_type=license_type,
                                encumbered_status=matching_license_in_current_jurisdiction.encumberedStatus,
                            )
                            continue

                        # Get transaction items for privileges that can be moved to a license in the new jurisdiction
                        privilege_transaction_items = (
                            self._get_privilege_transaction_items_resulting_from_home_jurisdiction_move(
                                compact=compact,
                                provider_id=provider_id,
                                provider_user_records=provider_user_records,
                                selected_jurisdiction=selected_jurisdiction,
                                license_type=license_type,
                            )
                        )
                        all_transaction_items.extend(privilege_transaction_items)

            # Execute all transactions in batches
            self._execute_batched_transactions(all_transaction_items)

            # Return the previous home jurisdiction
            return home_jurisdiction_before_update

        except Exception as e:
            logger.error(
                'Failed to update provider home state jurisdiction',
                compact=compact,
                provider_id=provider_id,
                selected_jurisdiction=selected_jurisdiction,
                error=str(e),
            )
            raise CCInternalException('Failed to update provider home state jurisdiction') from e

    def _execute_batched_transactions(self, transaction_items: list[dict]) -> None:
        """
        Execute transaction items in batches of 100 (DynamoDB limit).

        :param transaction_items: List of transaction items to execute
        :raises CCInternalException: If any transaction batch fails
        """
        if not transaction_items:
            logger.info('No transaction items to execute')
            return

        logger.info('Executing batched transactions', total_items=len(transaction_items))

        batch_size = MAX_DYNAMODB_TRANSACTION_ITEMS
        processed_batches = []

        try:
            # Process transactions in batches
            for i in range(0, len(transaction_items), batch_size):
                batch = transaction_items[i : i + batch_size]
                logger.info(
                    'Executing transaction batch',
                    batch_number=len(processed_batches) + 1,
                    batch_size=len(batch),
                    total_batches=(len(transaction_items) + batch_size - 1) // batch_size,
                )

                self.config.dynamodb_client.transact_write_items(TransactItems=batch)
                processed_batches.append(batch)

        except Exception as e:
            logger.error(
                'Transaction batch failed',
                failed_batch_number=len(processed_batches) + 1,
                total_processed_batches=len(processed_batches),
                error=str(e),
            )
            raise CCInternalException(f'Transaction batch failed: {str(e)}') from e

    def _get_privilege_transaction_items_resulting_from_home_jurisdiction_move(
        self,
        *,
        compact: str,
        provider_id: str,
        provider_user_records: ProviderUserRecords,
        selected_jurisdiction: str,
        license_type: str,
    ) -> list[dict]:
        """
        Get transaction items for privileges that are affected by moving to a new jurisdiction.

        This method contains the common logic for determining if privileges should be:
        1. Deactivated because there's no matching license in the selected jurisdiction
        2. Deactivated because the matching license is not compact eligible
        3. Updated to reference the new license (potentially with encumbered status)

        :param compact: The compact name
        :param provider_id: The provider ID
        :param provider_user_records: Collection of records for provider, including privileges and licenses
        :param selected_jurisdiction: The jurisdiction the provider has selected through the api.
        :param license_type: The license type to check
        :return: List of transaction items
        """
        # Get privileges for this license type that were not previously deactivated
        privileges_for_license_type = [
            privilege
            for privilege in provider_user_records.get_privilege_records(
                filter_condition=lambda p: (
                    p.licenseType == license_type
                    and p.homeJurisdictionChangeStatus != HomeJurisdictionChangeStatusEnum.INACTIVE
                )
            )
        ]

        if not privileges_for_license_type:
            logger.info('No active privileges found for license type.', license_type=license_type)
            return []

        licenses_in_selected_jurisdiction = provider_user_records.get_license_records(
            filter_condition=lambda license_data: license_data.jurisdiction == selected_jurisdiction
        )

        # Find matching license in new jurisdiction
        matching_license_in_selected_jurisdiction = next(
            (
                license_data
                for license_data in licenses_in_selected_jurisdiction
                if license_data.licenseType == license_type
            ),
            None,
        )

        if not matching_license_in_selected_jurisdiction:
            logger.info(
                'No matching license in new jurisdiction for license type. Deactivating privileges.',
                license_type=license_type,
            )
            # Return transaction items for deactivating privileges if no matching license in new jurisdiction
            return self._get_privilege_deactivation_transaction_items_for_jurisdiction_change(
                compact=compact, provider_id=provider_id, privileges=privileges_for_license_type
            )

        # Check if new license is compact eligible
        if (
            matching_license_in_selected_jurisdiction.jurisdictionUploadedCompactEligibility
            == CompactEligibilityStatus.INELIGIBLE
        ):
            logger.info('License in selected jurisdiction is not compact eligible')
            return self._get_privilege_deactivation_transaction_items_for_jurisdiction_change(
                compact=compact, provider_id=provider_id, privileges=privileges_for_license_type
            )

        # Return transaction items for updating privileges based on their current state
        return self._get_privilege_update_transaction_items_for_jurisdiction_change(
            compact=compact,
            provider_id=provider_id,
            privileges=privileges_for_license_type,
            new_license=matching_license_in_selected_jurisdiction,
        )

    def _get_provider_record_transaction_items_for_jurisdiction_with_no_known_license(
        self,
        *,
        compact: str,
        provider_id: str,
        provider_record: ProviderData,
        selected_jurisdiction: str,
    ) -> list[dict]:
        """
        Get transaction items for updating the provider record when changing to a
        jurisdiction for which we do not have a license on file.

        :param compact: The compact name
        :param provider_id: The provider ID
        :param provider_record: The current provider record
        :param selected_jurisdiction: The selected non-member jurisdiction
        :return: List of transaction items
        """
        logger.info(
            'Updating provider record for jurisdiction with no known license',
            compact=compact,
            provider_id=provider_id,
            new_jurisdiction=selected_jurisdiction,
        )

        # Create the provider update record
        now = config.current_standard_datetime
        provider_update_record = ProviderUpdateData.create_new(
            {
                'type': ProviderRecordType.PROVIDER_UPDATE,
                'updateType': UpdateCategory.HOME_JURISDICTION_CHANGE,
                'providerId': provider_id,
                'compact': compact,
                'previous': provider_record.to_dict(),
                'createDate': now,
                'updatedValues': {
                    'currentHomeJurisdiction': selected_jurisdiction,
                },
            }
        )

        # Create transaction items for the provider update
        return [
            # Create provider update record
            {
                'Put': {
                    'TableName': self.config.provider_table_name,
                    'Item': TypeSerializer().serialize(provider_update_record.serialize_to_database_record())['M'],
                }
            },
            # Update provider record. In this case, we set the current home jurisdiction without setting any new license
            # values, since there is no new license.
            {
                'Update': {
                    'TableName': self.config.provider_table_name,
                    'Key': {
                        'pk': {'S': f'{compact}#PROVIDER#{provider_id}'},
                        'sk': {'S': f'{compact}#PROVIDER'},
                    },
                    'UpdateExpression': 'SET '
                    'currentHomeJurisdiction = :currentHomeJurisdiction, '
                    'dateOfUpdate = :dateOfUpdate, '
                    'providerDateOfUpdate = :providerDateOfUpdate',
                    'ExpressionAttributeValues': {
                        ':currentHomeJurisdiction': {'S': selected_jurisdiction},
                        ':dateOfUpdate': {'S': now.isoformat()},
                        ':providerDateOfUpdate': {'S': now.isoformat()},
                    },
                    'ConditionExpression': 'attribute_exists(pk)',
                }
            },
        ]

    def _get_privilege_deactivation_transaction_items_for_jurisdiction_change(
        self,
        *,
        compact: str,
        provider_id: str,
        privileges: list[PrivilegeData],
    ) -> list[dict]:
        """
        Get transaction items for deactivating privileges when changing to a jurisdiction where they can't be valid.

        Note: This method is designed to handle up to 50 privileges in a single transaction.
        We don't anticipate a system with more than 50 jurisdictions for the foreseeable future,
        so this limit is sufficient.
        If the system grows beyond 50 jurisdictions, this method will need to be enhanced to
        process multiple transactions with proper rollback handling.

        :param compact: The compact name
        :param provider_id: The provider ID
        :param privileges: The list of privileges to deactivate
        :return: List of transaction items
        """
        if not privileges:
            logger.info(
                'No privileges provided to deactivate for jurisdiction change',
                compact=compact,
                provider_id=provider_id,
            )
            return []

        logger.info(
            'Deactivating privileges for jurisdiction change',
            compact=compact,
            provider_id=provider_id,
            num_privileges=len(privileges),
        )

        transactions = []

        now = config.current_standard_datetime

        for privilege in privileges:
            # Create update record
            privilege_update_record = PrivilegeUpdateData.create_new(
                {
                    'type': ProviderRecordType.PRIVILEGE_UPDATE,
                    'updateType': UpdateCategory.HOME_JURISDICTION_CHANGE,
                    'providerId': provider_id,
                    'compact': compact,
                    'jurisdiction': privilege.jurisdiction,
                    'licenseType': privilege.licenseType,
                    'createDate': now,
                    'effectiveDate': now,
                    'previous': privilege.to_dict(),
                    'updatedValues': {
                        'homeJurisdictionChangeStatus': HomeJurisdictionChangeStatusEnum.INACTIVE,
                        'dateOfUpdate': self.config.current_standard_datetime,
                    },
                }
            )

            # Add update record to transaction
            transactions.append(
                {
                    'Put': {
                        'TableName': self.config.provider_table_name,
                        'Item': TypeSerializer().serialize(privilege_update_record.serialize_to_database_record())['M'],
                    }
                }
            )

            # Update privilege record
            transactions.append(
                {
                    'Update': {
                        'TableName': self.config.provider_table_name,
                        'Key': {
                            'pk': {'S': privilege.serialize_to_database_record()['pk']},
                            'sk': {'S': privilege.serialize_to_database_record()['sk']},
                        },
                        'UpdateExpression': 'SET homeJurisdictionChangeStatus = :homeJurisdictionChangeStatus,'
                        'dateOfUpdate = :dateOfUpdate',
                        'ExpressionAttributeValues': {
                            ':homeJurisdictionChangeStatus': {'S': HomeJurisdictionChangeStatusEnum.INACTIVE},
                            ':dateOfUpdate': {'S': self.config.current_standard_datetime.isoformat()},
                        },
                    }
                }
            )

        return transactions

    def _get_provider_record_transaction_items_for_jurisdiction_change_with_license(
        self,
        *,
        compact: str,
        provider_id: str,
        provider_records: ProviderUserRecords,
        new_license_record: LicenseData,
        selected_jurisdiction: str,
    ) -> list[dict]:
        """
        Get transaction items for updating the provider record when changing to a new best license.

        :param compact: The compact name
        :param provider_id: The provider ID
        :param provider_records: All the records for this provider
        :param new_license_record: The best license in the new jurisdiction
        :param selected_jurisdiction: The selected jurisdiction
        :return: List of transaction items
        """
        logger.info(
            'Updating provider record with information from new best license',
            compact=compact,
            provider_id=provider_id,
            license_jurisdiction=new_license_record.jurisdiction,
        )

        # Create the provider update record
        now = config.current_standard_datetime
        provider_update_record = ProviderUpdateData.create_new(
            {
                'type': ProviderRecordType.PROVIDER_UPDATE,
                'updateType': UpdateCategory.HOME_JURISDICTION_CHANGE,
                'providerId': provider_id,
                'compact': compact,
                'previous': provider_records.get_provider_record().to_dict(),
                'createDate': now,
                'updatedValues': {
                    'licenseJurisdiction': new_license_record.jurisdiction,
                    # we explicitly set this to align with what was passed in as the selected jurisdiction
                    'currentHomeJurisdiction': selected_jurisdiction,
                },
            }
        )

        # Create transaction items for the provider update
        transactions = [
            # Create provider update record
            {
                'Put': {
                    'TableName': self.config.provider_table_name,
                    'Item': TypeSerializer().serialize(provider_update_record.serialize_to_database_record())['M'],
                }
            },
        ]
        # populate the provider record with the fields from the new license
        provider_record = ProviderRecordUtility.populate_provider_record(
            current_provider_record=provider_records.get_provider_record(),
            license_record=new_license_record.to_dict(),
            privilege_records=[privilege.to_dict() for privilege in provider_records.get_privilege_records()],
        )
        provider_record.update({'currentHomeJurisdiction': selected_jurisdiction})
        transactions.append(
            {
                'Put': {
                    'TableName': config.provider_table_name,
                    'Item': TypeSerializer().serialize(provider_record.serialize_to_database_record())['M'],
                }
            }
        )

        return transactions

    def _get_privilege_update_transaction_items_for_jurisdiction_change(
        self,
        *,
        compact: str,
        provider_id: str,
        privileges: list[PrivilegeData],
        new_license: LicenseData,
    ) -> list[dict]:
        """
        Get transaction items for updating privileges when changing to a jurisdiction with a valid license.

        Note: This method is designed to handle up to 50 privileges in a single transaction.
        The current system supports a maximum of 50 jurisdictions, so this limit is sufficient.
        If the system grows beyond 50 jurisdictions, this method will need to be enhanced to
        process multiple transactions with proper rollback handling.

        :param compact: The compact name
        :param provider_id: The provider ID
        :param privileges: The list of privileges to update
        :param new_license: The license in the new jurisdiction
        :return: List of transaction items
        """
        if not privileges:
            logger.info(
                'No privileges provided to update for jurisdiction change with valid license',
                compact=compact,
                provider_id=provider_id,
                new_jurisdiction=new_license.jurisdiction,
                license_type=new_license.licenseType,
            )
            return []

        is_new_license_encumbered = new_license.encumberedStatus == LicenseEncumberedStatusEnum.ENCUMBERED

        logger.info(
            'Updating privileges for jurisdiction change with valid license',
            compact=compact,
            provider_id=provider_id,
            new_jurisdiction=new_license.jurisdiction,
            num_privileges=len(privileges),
            is_new_license_encumbered=is_new_license_encumbered,
            license_type=new_license.licenseType,
            license_expiration=new_license.dateOfExpiration,
        )

        transactions = []

        for privilege in privileges:
            # if the privilege is for the same jurisdiction as the new license,
            # then we deactivate it
            if privilege.jurisdiction == new_license.jurisdiction:
                logger.info(
                    'Privilege is for the same jurisdiction as the new license. Deactivating privilege.',
                    privilege_id=privilege.privilegeId,
                    privilege_jurisdiction=privilege.jurisdiction,
                    new_license_jurisdiction=new_license.jurisdiction,
                    privilege_license_type=privilege.licenseType,
                )
                # Get transaction items for deactivating this privilege and add them to our transactions
                deactivation_transactions = self._get_privilege_deactivation_transaction_items_for_jurisdiction_change(
                    compact=compact, provider_id=provider_id, privileges=[privilege]
                )
                transactions.extend(deactivation_transactions)
                continue

            # Check if privilege was previously deactivated due to a home jurisdiction change.
            # If the privilege was renewed after the last jurisdiction update, this field should
            # not be present.
            if privilege.homeJurisdictionChangeStatus is not None:
                logger.info(
                    'Privilege was previously deactivated due to home jurisdiction change. '
                    'Will not move privilege over.',
                    privilege_id=privilege.privilegeId,
                    privilege_jurisdiction=privilege.jurisdiction,
                    privilege_license_type=privilege.licenseType,
                )
                continue

            updated_values = {
                'licenseJurisdiction': new_license.jurisdiction,
                'dateOfExpiration': new_license.dateOfExpiration,
            }

            # When a home state license is encumbered, all associated privileges for that license must be
            # encumbered as well. We use the 'LICENSE_ENCUMBERED' status type to denote the encumbrance on the privilege
            # is the result of a home state license being encumbered, rather than a state setting an encumbrance on an
            # individual privilege directly. If a state sets an encumbrance on a privilege record directly, it will be
            # in an 'ENCUMBERED' status.
            #
            # When changing home states, if the new home state license is encumbered, we set the privileges for that
            # license type to a 'LICENSE_ENCUMBERED' status unless the privilege itself has already been encumbered with
            # an 'ENCUMBERED' status.
            if is_new_license_encumbered and privilege.encumberedStatus != PrivilegeEncumberedStatusEnum.ENCUMBERED:
                logger.info(
                    'New license record is encumbered and privilege is not already encumbered. Apply encumbered status.'
                )
                updated_values['encumberedStatus'] = PrivilegeEncumberedStatusEnum.LICENSE_ENCUMBERED

            now = config.current_standard_datetime

            # Create update record
            privilege_update_record = PrivilegeUpdateData.create_new(
                {
                    'type': ProviderRecordType.PRIVILEGE_UPDATE,
                    'updateType': UpdateCategory.HOME_JURISDICTION_CHANGE,
                    'providerId': provider_id,
                    'compact': compact,
                    'jurisdiction': privilege.jurisdiction,
                    'createDate': now,
                    'effectiveDate': now,
                    'licenseType': privilege.licenseType,
                    'previous': privilege.to_dict(),
                    'updatedValues': updated_values,
                }
            )

            # Add update record to transaction
            transactions.append(
                {
                    'Put': {
                        'TableName': self.config.provider_table_name,
                        'Item': TypeSerializer().serialize(privilege_update_record.serialize_to_database_record())['M'],
                    }
                }
            )

            # Update privilege record
            set_clauses = [
                'licenseJurisdiction = :licenseJurisdiction',
                'dateOfExpiration = :dateOfExpiration',
                'dateOfUpdate = :dateOfUpdate',
            ]
            expression_values = {
                ':licenseJurisdiction': {'S': new_license.jurisdiction},
                ':dateOfExpiration': {'S': new_license.dateOfExpiration.isoformat()},
                ':dateOfUpdate': {'S': self.config.current_standard_datetime.isoformat()},
            }

            if is_new_license_encumbered:
                set_clauses.append('encumberedStatus = :encumberedStatus')
                expression_values[':encumberedStatus'] = {'S': updated_values['encumberedStatus']}

            # Build the final update expression
            update_expression = 'SET ' + ', '.join(set_clauses)

            serialized_privilege_record = privilege.serialize_to_database_record()

            transactions.append(
                {
                    'Update': {
                        'TableName': self.config.provider_table_name,
                        'Key': {
                            'pk': {'S': serialized_privilege_record['pk']},
                            'sk': {'S': serialized_privilege_record['sk']},
                        },
                        'UpdateExpression': update_expression,
                        'ExpressionAttributeValues': expression_values,
                    }
                }
            )

        return transactions

    @logger_inject_kwargs(logger, 'compact', 'provider_id')
    def update_provider_email_verification_data(
        self,
        *,
        compact: str,
        provider_id: str,
        pending_email_address: str,
        verification_code: str,
        verification_expiry: datetime,
    ) -> None:
        """
        Update the provider record with email verification data.

        :param compact: The compact name
        :param provider_id: The provider ID
        :param pending_email_address: The new email address being verified
        :param verification_code: The 4-digit verification code
        :param verification_expiry: When the verification code expires
        """
        logger.info('Updating provider email verification data with pending values.')

        try:
            self.config.provider_table.update_item(
                Key={'pk': f'{compact}#PROVIDER#{provider_id}', 'sk': f'{compact}#PROVIDER'},
                UpdateExpression=(
                    'SET pendingEmailAddress = :pending_email, '
                    'emailVerificationCode = :verification_code, '
                    'emailVerificationExpiry = :verification_expiry, '
                    'dateOfUpdate = :date_of_update'
                ),
                ExpressionAttributeValues={
                    ':pending_email': pending_email_address,
                    ':verification_code': verification_code,
                    ':verification_expiry': verification_expiry.isoformat(),
                    ':date_of_update': self.config.current_standard_datetime.isoformat(),
                },
                # Ensure the provider record exists before updating
                ConditionExpression='attribute_exists(pk)',
            )
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                logger.error('Provider not found', error=str(e))
                raise CCInternalException('Provider not found') from e
            logger.error('Failed to update provider email verification data', error=str(e))
            raise CCAwsServiceException('Failed to update provider email verification data') from e

    @logger_inject_kwargs(logger, 'compact', 'provider_id')
    def clear_provider_email_verification_data(
        self,
        *,
        compact: str,
        provider_id: str,
    ) -> None:
        """
        Clear email verification data from the provider record.

        :param compact: The compact name
        :param provider_id: The provider ID
        """
        logger.info('Clearing provider email verification data')

        try:
            self.config.provider_table.update_item(
                Key={'pk': f'{compact}#PROVIDER#{provider_id}', 'sk': f'{compact}#PROVIDER'},
                UpdateExpression=(
                    'REMOVE pendingEmailAddress, emailVerificationCode, emailVerificationExpiry '
                    'SET dateOfUpdate = :date_of_update'
                ),
                ExpressionAttributeValues={
                    ':date_of_update': self.config.current_standard_datetime.isoformat(),
                },
                # Ensure the provider record exists before updating
                ConditionExpression='attribute_exists(pk)',
            )
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                raise CCNotFoundException('Provider not found') from e
            logger.error('Failed to clear provider email verification data', error=str(e))
            raise CCAwsServiceException('Failed to clear provider email verification data') from e

    @logger_inject_kwargs(logger, 'compact', 'provider_id')
    def complete_provider_email_update(
        self,
        *,
        compact: str,
        provider_id: str,
        new_email_address: str,
    ) -> None:
        """
        Complete the email update process by updating the registered email and clearing verification data.
        Creates a provider update record to track the email change.

        :param compact: The compact name
        :param provider_id: The provider ID
        :param new_email_address: The new verified email address
        """
        logger.info('Completing provider email update')

        # Get current provider record to capture the "previous" state
        current_provider_record = self.get_provider_top_level_record(compact=compact, provider_id=provider_id)

        # Create provider update record to track the email change
        now = config.current_standard_datetime
        provider_update_record = ProviderUpdateData.create_new(
            {
                'type': ProviderRecordType.PROVIDER_UPDATE,
                'updateType': UpdateCategory.EMAIL_CHANGE,
                'providerId': provider_id,
                'compact': compact,
                'previous': current_provider_record.to_dict(),
                'createDate': now,
                'updatedValues': {
                    'compactConnectRegisteredEmailAddress': new_email_address,
                },
            }
        )

        try:
            # Use a transaction to ensure both operations succeed together
            self.config.dynamodb_client.transact_write_items(
                TransactItems=[
                    # Update the provider record with new email and clear verification data
                    {
                        'Update': {
                            'TableName': self.config.provider_table_name,
                            'Key': {
                                'pk': {'S': f'{compact}#PROVIDER#{provider_id}'},
                                'sk': {'S': f'{compact}#PROVIDER'},
                            },
                            'UpdateExpression': (
                                'SET compactConnectRegisteredEmailAddress = :new_email, '
                                'dateOfUpdate = :date_of_update, '
                                'providerDateOfUpdate = :provider_date_of_update '
                                'REMOVE pendingEmailAddress, emailVerificationCode, emailVerificationExpiry'
                            ),
                            'ExpressionAttributeValues': {
                                ':new_email': {'S': new_email_address},
                                ':date_of_update': {'S': now.isoformat()},
                                ':provider_date_of_update': {'S': now.isoformat()},
                            },
                            # Ensure the provider record exists before updating
                            'ConditionExpression': 'attribute_exists(pk)',
                        }
                    },
                    # Create provider update record
                    {
                        'Put': {
                            'TableName': self.config.provider_table_name,
                            'Item': TypeSerializer().serialize(provider_update_record.serialize_to_database_record())[
                                'M'
                            ],
                        }
                    },
                ]
            )
        except ClientError as e:
            logger.error('Failed to complete provider email update transaction', error=str(e))
            raise CCAwsServiceException('Failed to complete provider email update') from e

    @logger_inject_kwargs(logger, 'compact', 'provider_id')
    def update_provider_account_recovery_data(
        self,
        *,
        compact: str,
        provider_id: str,
        recovery_token: str,
        recovery_expiry: datetime,
    ) -> None:
        """
        Update the provider record with MFA account recovery data (UUID and expiry).

        :param compact: The compact name
        :param provider_id: The provider ID
        :param recovery_token: The recovery UUID to store
        :param recovery_expiry: The expiration datetime of the recovery UUID
        """
        logger.info('Updating provider account recovery data')

        try:
            self.config.provider_table.update_item(
                Key={'pk': f'{compact}#PROVIDER#{provider_id}', 'sk': f'{compact}#PROVIDER'},
                UpdateExpression=(
                    'SET recoveryToken = :recovery_token, '
                    'recoveryExpiry = :recovery_expiry, '
                    'dateOfUpdate = :date_of_update'
                ),
                ExpressionAttributeValues={
                    ':recovery_token': recovery_token,
                    ':recovery_expiry': recovery_expiry.isoformat(),
                    ':date_of_update': self.config.current_standard_datetime.isoformat(),
                },
                ConditionExpression='attribute_exists(pk)',
            )
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                logger.error('Provider not found when updating account recovery data', error=str(e))
                raise CCInternalException('Provider not found') from e
            logger.error('Failed to update provider account recovery data', error=str(e))
            raise CCAwsServiceException('Failed to update provider account recovery data') from e

    @logger_inject_kwargs(logger, 'compact', 'provider_id')
    def clear_provider_account_recovery_data(
        self,
        *,
        compact: str,
        provider_id: str,
    ) -> None:
        """
        Clear account recovery data from the provider record.

        :param compact: The compact name
        :param provider_id: The provider ID
        """
        logger.info('Clearing provider account recovery data')

        try:
            self.config.provider_table.update_item(
                Key={'pk': f'{compact}#PROVIDER#{provider_id}', 'sk': f'{compact}#PROVIDER'},
                UpdateExpression=('REMOVE recoveryToken, recoveryExpiry SET dateOfUpdate = :date_of_update'),
                ExpressionAttributeValues={
                    ':date_of_update': self.config.current_standard_datetime.isoformat(),
                },
                ConditionExpression='attribute_exists(pk)',
            )
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                raise CCInternalException('Provider not found') from e
            logger.error('Failed to clear provider account recovery data', error=str(e))
            raise CCInternalException('Failed to clear provider account recovery data') from e
