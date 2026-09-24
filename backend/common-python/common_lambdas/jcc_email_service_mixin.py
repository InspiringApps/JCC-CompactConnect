# Copied method bodies from backend/compact-connect/lambdas/python/common/cc_common/email_service_client.py

from datetime import date
from typing import Any
from uuid import UUID

from common_lambdas.exceptions import CCInternalException


class JccEmailServiceClientMixin:
    def send_compact_transaction_report_email(
        self,
        compact: str,
        report_s3_path: str,
        reporting_cycle: str,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        """
        Send a compact transaction report email.

        :param compact: Compact name
        :param report_s3_path: S3 path to the report zip file
        :param reporting_cycle: Reporting cycle (e.g., 'weekly', 'monthly')
        :param start_date: Start date of the reporting period
        :param end_date: End date of the reporting period
        :return: Response from the email notification service
        """

        payload = {
            'compact': compact,
            'template': 'CompactTransactionReporting',
            'recipientType': 'COMPACT_SUMMARY_REPORT',
            'templateVariables': {
                'reportS3Path': report_s3_path,
                'reportingCycle': reporting_cycle,
                'startDate': start_date.strftime('%Y-%m-%d'),
                'endDate': end_date.strftime('%Y-%m-%d'),
            },
        }

        return self._invoke_lambda(payload)

    def send_jurisdiction_transaction_report_email(
        self,
        compact: str,
        jurisdiction: str,
        report_s3_path: str,
        reporting_cycle: str,
        start_date: date,
        end_date: date,
    ) -> dict[str, str]:
        """
        Send a jurisdiction transaction report email.

        :param compact: Compact name
        :param jurisdiction: Jurisdiction name
        :param report_s3_path: S3 path to the report zip file
        :param reporting_cycle: Reporting cycle (e.g., 'weekly', 'monthly')
        :param start_date: Start date of the reporting period
        :param end_date: End date of the reporting period
        :return: Response from the email notification service
        """

        payload = {
            'compact': compact,
            'jurisdiction': jurisdiction,
            'template': 'JurisdictionTransactionReporting',
            'recipientType': 'JURISDICTION_SUMMARY_REPORT',
            'templateVariables': {
                'reportS3Path': report_s3_path,
                'reportingCycle': reporting_cycle,
                'startDate': start_date.strftime('%Y-%m-%d'),
                'endDate': end_date.strftime('%Y-%m-%d'),
            },
        }
    def send_provider_email_verification_code(
        self,
        compact: str,
        provider_email: str,
        verification_code: str,
    ) -> dict[str, str]:
        """
        Send an email verification code to a provider's new email address.

        :param compact: Compact name
        :param provider_email: Email address to send the verification code to
        :param verification_code: 4-digit verification code
        :return: Response from the email notification service
        """
        payload = {
            'compact': compact,
            'template': 'providerEmailVerificationCode',
            'recipientType': 'SPECIFIC',
            'specificEmails': [
                provider_email,
            ],
            'templateVariables': {
                'verificationCode': verification_code,
            },
        }

        return self._invoke_lambda(payload)

    def send_provider_email_change_notification(
        self,
        compact: str,
        old_email_address: str,
        new_email_address: str,
    ) -> dict[str, str]:
        """
        Send a notification to the old email address when a provider's email is changed.

        :param compact: Compact name
        :param old_email_address: The previous email address
        :param new_email_address: The new email address
        :return: Response from the email notification service
        """
        payload = {
            'compact': compact,
            'template': 'providerEmailChangeNotification',
            'recipientType': 'SPECIFIC',
            'specificEmails': [
                old_email_address,
            ],
            'templateVariables': {
                'newEmailAddress': new_email_address,
            },
        }

        return self._invoke_lambda(payload)

    def send_provider_account_recovery_confirmation_email(
        self,
        *,
        compact: str,
        provider_email: str,
        provider_id: str,
        recovery_token: str,
    ) -> dict[str, str]:
        """
        Send an account recovery confirmation email to a provider with a secure link.

        :param compact: The compact name
        :param provider_email: Email address of the provider
        :param provider_id: The id of the provider
        :param recovery_token: Recovery token
        :return: Response from the email notification service
        """

        payload = {
            'compact': compact,
            'template': 'providerAccountRecoveryConfirmation',
            'recipientType': 'SPECIFIC',
            'specificEmails': [provider_email],
            'templateVariables': {
                'providerId': str(provider_id),
                'recoveryToken': str(recovery_token),
            },
        }

        return self._invoke_lambda(payload)
    def send_home_jurisdiction_change_old_state_notification(
        self,
        *,
        compact: str,
        jurisdiction: str,
        provider_first_name: str,
        provider_last_name: str,
        provider_id: UUID,
        new_jurisdiction: str,
    ) -> dict[str, str]:
        """
        Notify the old home state that a practitioner has changed their home jurisdiction.

        :param compact: Compact name
        :param jurisdiction: Old jurisdiction to notify
        :param provider_first_name: Provider's first name
        :param provider_last_name: Provider's last name
        :param provider_id: Provider ID
        :param new_jurisdiction: New home jurisdiction
        :return: Response from the email notification service
        """
        payload = {
            'compact': compact,
            'jurisdiction': jurisdiction,
            'template': 'homeJurisdictionChangeOldStateNotification',
            'recipientType': 'JURISDICTION_OPERATIONS_TEAM',
            'templateVariables': {
                'providerFirstName': provider_first_name,
                'providerLastName': provider_last_name,
                'providerId': str(provider_id),
                'previousJurisdiction': jurisdiction,
                'newJurisdiction': new_jurisdiction,
            },
        }
        return self._invoke_lambda(payload)

    def send_home_jurisdiction_change_new_state_notification(
        self,
        *,
        compact: str,
        jurisdiction: str,
        provider_first_name: str,
        provider_last_name: str,
        provider_id: UUID,
        previous_jurisdiction: str,
    ) -> dict[str, str]:
        """
        Notify the new home state that a practitioner has selected them as their home jurisdiction.

        :param compact: Compact name
        :param jurisdiction: New jurisdiction to notify
        :param provider_first_name: Provider's first name
        :param provider_last_name: Provider's last name
        :param provider_id: Provider ID
        :param previous_jurisdiction: Previous home jurisdiction
        :return: Response from the email notification service
        """
        payload = {
            'compact': compact,
            'jurisdiction': jurisdiction,
            'template': 'homeJurisdictionChangeNewStateNotification',
            'recipientType': 'JURISDICTION_OPERATIONS_TEAM',
            'templateVariables': {
                'providerFirstName': provider_first_name,
                'providerLastName': provider_last_name,
                'providerId': str(provider_id),
                'previousJurisdiction': previous_jurisdiction,
                'newJurisdiction': jurisdiction,
            },
        }
        return self._invoke_lambda(payload)
