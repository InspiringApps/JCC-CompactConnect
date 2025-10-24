import json
from datetime import datetime
from unittest.mock import patch
from uuid import UUID, uuid4

from common_test.test_constants import (
    DEFAULT_COMPACT,
    DEFAULT_DATE_OF_UPDATE_TIMESTAMP,
    DEFAULT_LICENSE_JURISDICTION,
    DEFAULT_LICENSE_TYPE_ABBREVIATION,
    DEFAULT_PRIVILEGE_JURISDICTION,
    DEFAULT_PROVIDER_ID,
)
from moto import mock_aws

from . import TstFunction


@mock_aws
@patch('cc_common.config._Config.current_standard_datetime', datetime.fromisoformat(DEFAULT_DATE_OF_UPDATE_TIMESTAMP))
class TestInvestigationEvents(TstFunction):
    """Test suite for investigation event handlers."""

    def _generate_license_investigation_message(self, message_overrides=None):
        """Generate a test SQS message for license investigation events."""
        message = {
            'detail': {
                'compact': DEFAULT_COMPACT,
                'providerId': DEFAULT_PROVIDER_ID,
                'jurisdiction': DEFAULT_LICENSE_JURISDICTION,
                'licenseTypeAbbreviation': DEFAULT_LICENSE_TYPE_ABBREVIATION,
                'eventTime': DEFAULT_DATE_OF_UPDATE_TIMESTAMP,
                'investigationAgainst': 'license',
                'investigationId': str(uuid4()),
            }
        }
        if message_overrides:
            message['detail'].update(message_overrides)
        return message

    def _generate_license_investigation_closed_message(self, message_overrides=None):
        """Generate a test SQS message for license investigation closed events."""
        message = {
            'detail': {
                'compact': DEFAULT_COMPACT,
                'providerId': DEFAULT_PROVIDER_ID,
                'jurisdiction': DEFAULT_LICENSE_JURISDICTION,
                'licenseTypeAbbreviation': DEFAULT_LICENSE_TYPE_ABBREVIATION,
                'eventTime': DEFAULT_DATE_OF_UPDATE_TIMESTAMP,
                'investigationAgainst': 'license',
                'investigationId': str(uuid4()),
            }
        }
        if message_overrides:
            message['detail'].update(message_overrides)
        return message

    def _generate_privilege_investigation_message(self, message_overrides=None):
        """Generate a test SQS message for privilege investigation events."""
        message = {
            'detail': {
                'compact': DEFAULT_COMPACT,
                'providerId': DEFAULT_PROVIDER_ID,
                'jurisdiction': DEFAULT_PRIVILEGE_JURISDICTION,
                'licenseTypeAbbreviation': DEFAULT_LICENSE_TYPE_ABBREVIATION,
                'eventTime': DEFAULT_DATE_OF_UPDATE_TIMESTAMP,
                'investigationAgainst': 'privilege',
                'investigationId': str(uuid4()),
            }
        }
        if message_overrides:
            message['detail'].update(message_overrides)
        return message

    def _generate_privilege_investigation_closed_message(self, message_overrides=None):
        """Generate a test SQS message for privilege investigation closed events."""
        message = {
            'detail': {
                'compact': DEFAULT_COMPACT,
                'providerId': DEFAULT_PROVIDER_ID,
                'jurisdiction': DEFAULT_PRIVILEGE_JURISDICTION,
                'licenseTypeAbbreviation': DEFAULT_LICENSE_TYPE_ABBREVIATION,
                'eventTime': DEFAULT_DATE_OF_UPDATE_TIMESTAMP,
                'investigationAgainst': 'privilege',
                'investigationId': str(uuid4()),
            }
        }
        if message_overrides:
            message['detail'].update(message_overrides)
        return message

    def _create_sqs_event(self, message):
        """Create a proper SQS event structure with the message in the body."""
        return {'Records': [{'messageId': '123', 'body': json.dumps(message)}]}

    @patch('cc_common.email_service_client.EmailServiceClient.send_license_investigation_state_notification_email')
    @patch('cc_common.email_service_client.EmailServiceClient.send_license_investigation_provider_notification_email')
    def test_license_investigation_listener_processes_event_with_registered_provider(
        self, mock_provider_email, mock_state_email
    ):
        """Test that license investigation listener processes events for registered providers."""
        from cc_common.email_service_client import InvestigationNotificationTemplateVariables
        from handlers.investigation_events import license_investigation_notification_listener

        # Set up test data with registered provider
        self.test_data_generator.put_default_provider_record_in_provider_table(
            value_overrides={'compactConnectRegisteredEmailAddress': 'provider@example.com'}
        )

        # Add the license that is under investigation
        self.test_data_generator.put_default_license_record_in_provider_table()

        # Create additional licenses and privileges for notification testing
        self.test_data_generator.put_default_license_record_in_provider_table(
            value_overrides={
                'jurisdiction': 'co',
                'jurisdictionUploadedLicenseStatus': 'active',
            }
        )
        self.test_data_generator.put_default_privilege_record_in_provider_table(
            value_overrides={
                'jurisdiction': 'ky',
                'administratorSetStatus': 'active',
            }
        )

        message = self._generate_license_investigation_message()
        event = self._create_sqs_event(message)

        # Execute the handler
        result = license_investigation_notification_listener(event, self.mock_context)

        # Should succeed with no batch failures
        self.assertEqual({'batchItemFailures': []}, result)

        # Verify provider notification
        mock_provider_email.assert_called_once_with(
            compact=DEFAULT_COMPACT,
            provider_email='provider@example.com',
            template_variables=InvestigationNotificationTemplateVariables(
                provider_first_name='Björk',
                provider_last_name='Guðmundsdóttir',
                investigation_jurisdiction=DEFAULT_LICENSE_JURISDICTION,
                license_type='speech-language pathologist',
                provider_id=None,
            ),
        )

        # Verify state notifications (investigation state + other states with active licenses/privileges)
        expected_template_variables_oh = InvestigationNotificationTemplateVariables(
            provider_first_name='Björk',
            provider_last_name='Guðmundsdóttir',
            investigation_jurisdiction=DEFAULT_LICENSE_JURISDICTION,
            license_type='speech-language pathologist',
            provider_id=UUID(DEFAULT_PROVIDER_ID),
        )
        expected_template_variables_co = InvestigationNotificationTemplateVariables(
            provider_first_name='Björk',
            provider_last_name='Guðmundsdóttir',
            investigation_jurisdiction=DEFAULT_LICENSE_JURISDICTION,
            license_type='speech-language pathologist',
            provider_id=UUID(DEFAULT_PROVIDER_ID),
        )
        expected_template_variables_ky = InvestigationNotificationTemplateVariables(
            provider_first_name='Björk',
            provider_last_name='Guðmundsdóttir',
            investigation_jurisdiction=DEFAULT_LICENSE_JURISDICTION,
            license_type='speech-language pathologist',
            provider_id=UUID(DEFAULT_PROVIDER_ID),
        )
        expected_state_calls = [
            # State 'oh' (investigation jurisdiction)
            {
                'compact': DEFAULT_COMPACT,
                'jurisdiction': DEFAULT_LICENSE_JURISDICTION,
                'template_variables': expected_template_variables_oh,
            },
            # State 'co' (active license jurisdiction)
            {
                'compact': DEFAULT_COMPACT,
                'jurisdiction': 'co',
                'template_variables': expected_template_variables_co,
            },
            # State 'ky' (active privilege jurisdiction)
            {
                'compact': DEFAULT_COMPACT,
                'jurisdiction': 'ky',
                'template_variables': expected_template_variables_ky,
            },
        ]

        # Verify all state notifications were sent
        self.assertEqual(3, mock_state_email.call_count)
        actual_state_calls = [call.kwargs for call in mock_state_email.call_args_list]

        # Sort both lists for comparison
        expected_state_calls_sorted = sorted(expected_state_calls, key=lambda x: x['jurisdiction'])
        actual_state_calls_sorted = sorted(actual_state_calls, key=lambda x: x['jurisdiction'])

        self.assertEqual(expected_state_calls_sorted, actual_state_calls_sorted)

    @patch('cc_common.email_service_client.EmailServiceClient.send_license_investigation_state_notification_email')
    @patch('cc_common.email_service_client.EmailServiceClient.send_license_investigation_provider_notification_email')
    def test_license_investigation_listener_processes_event_with_unregistered_provider(
        self, mock_provider_email, mock_state_email
    ):
        """
        Test that license investigation listener handles unregistered providers.

        Note: An unregistered provider holding a license should not be possible in our system.
        This test is just stressing the limits of our investigation logic, to make sure it handles it gracefully.
        """
        from cc_common.email_service_client import InvestigationNotificationTemplateVariables
        from handlers.investigation_events import license_investigation_notification_listener

        # Set up test data with unregistered provider (no email)
        self.test_data_generator.put_default_provider_record_in_provider_table(is_registered=False)

        # Add the license that is under investigation
        self.test_data_generator.put_default_license_record_in_provider_table()

        message = self._generate_license_investigation_message()
        event = self._create_sqs_event(message)

        # Execute the handler
        result = license_investigation_notification_listener(event, self.mock_context)

        # Should succeed with no batch failures
        self.assertEqual({'batchItemFailures': []}, result)

        # Verify no provider notification was sent
        mock_provider_email.assert_not_called()

        # Verify state notification was still sent
        mock_state_email.assert_called_once_with(
            compact=DEFAULT_COMPACT,
            jurisdiction=DEFAULT_LICENSE_JURISDICTION,
            template_variables=InvestigationNotificationTemplateVariables(
                provider_first_name='Björk',
                provider_last_name='Guðmundsdóttir',
                investigation_jurisdiction=DEFAULT_LICENSE_JURISDICTION,
                license_type='speech-language pathologist',
                provider_id=UUID(DEFAULT_PROVIDER_ID),
            ),
        )

    @patch(
        'cc_common.email_service_client.EmailServiceClient.send_license_investigation_closed_state_notification_email'
    )
    @patch(
        'cc_common.email_service_client.EmailServiceClient.send_license_investigation_closed_provider_notification_email'
    )
    def test_license_investigation_closed_listener_processes_event_with_registered_provider(
        self, mock_provider_email, mock_state_email
    ):
        """Test that license investigation closed listener processes events for registered providers."""
        from cc_common.email_service_client import InvestigationNotificationTemplateVariables
        from handlers.investigation_events import license_investigation_closed_notification_listener

        # Set up test data with registered provider
        self.test_data_generator.put_default_provider_record_in_provider_table(
            value_overrides={'compactConnectRegisteredEmailAddress': 'provider@example.com'}
        )

        # Add the license that was under investigation
        self.test_data_generator.put_default_license_record_in_provider_table()

        # Create additional licenses and privileges for notification testing
        self.test_data_generator.put_default_license_record_in_provider_table(
            value_overrides={
                'jurisdiction': 'co',
                'jurisdictionUploadedLicenseStatus': 'active',
            }
        )
        self.test_data_generator.put_default_privilege_record_in_provider_table(
            value_overrides={
                'jurisdiction': 'ky',
                'administratorSetStatus': 'active',
            }
        )

        message = self._generate_license_investigation_closed_message()
        event = self._create_sqs_event(message)

        # Execute the handler
        result = license_investigation_closed_notification_listener(event, self.mock_context)

        # Should succeed with no batch failures
        self.assertEqual({'batchItemFailures': []}, result)

        # Verify provider notification
        mock_provider_email.assert_called_once_with(
            compact=DEFAULT_COMPACT,
            provider_email='provider@example.com',
            template_variables=InvestigationNotificationTemplateVariables(
                provider_first_name='Björk',
                provider_last_name='Guðmundsdóttir',
                investigation_jurisdiction=DEFAULT_LICENSE_JURISDICTION,
                license_type='speech-language pathologist',
                provider_id=None,
            ),
        )

        # Verify state notifications (investigation state + other states with active licenses/privileges)
        expected_template_variables_oh = InvestigationNotificationTemplateVariables(
            provider_first_name='Björk',
            provider_last_name='Guðmundsdóttir',
            investigation_jurisdiction=DEFAULT_LICENSE_JURISDICTION,
            license_type='speech-language pathologist',
            provider_id=UUID(DEFAULT_PROVIDER_ID),
        )
        expected_template_variables_co = InvestigationNotificationTemplateVariables(
            provider_first_name='Björk',
            provider_last_name='Guðmundsdóttir',
            investigation_jurisdiction=DEFAULT_LICENSE_JURISDICTION,
            license_type='speech-language pathologist',
            provider_id=UUID(DEFAULT_PROVIDER_ID),
        )
        expected_template_variables_ky = InvestigationNotificationTemplateVariables(
            provider_first_name='Björk',
            provider_last_name='Guðmundsdóttir',
            investigation_jurisdiction=DEFAULT_LICENSE_JURISDICTION,
            license_type='speech-language pathologist',
            provider_id=UUID(DEFAULT_PROVIDER_ID),
        )
        expected_state_calls = [
            # State 'oh' (investigation jurisdiction)
            {
                'compact': DEFAULT_COMPACT,
                'jurisdiction': DEFAULT_LICENSE_JURISDICTION,
                'template_variables': expected_template_variables_oh,
            },
            # State 'co' (active license jurisdiction)
            {
                'compact': DEFAULT_COMPACT,
                'jurisdiction': 'co',
                'template_variables': expected_template_variables_co,
            },
            # State 'ky' (active privilege jurisdiction)
            {
                'compact': DEFAULT_COMPACT,
                'jurisdiction': 'ky',
                'template_variables': expected_template_variables_ky,
            },
        ]

        # Verify all state notifications were sent
        self.assertEqual(3, mock_state_email.call_count)
        actual_state_calls = [call.kwargs for call in mock_state_email.call_args_list]

        # Sort both lists for comparison
        expected_state_calls_sorted = sorted(expected_state_calls, key=lambda x: x['jurisdiction'])
        actual_state_calls_sorted = sorted(actual_state_calls, key=lambda x: x['jurisdiction'])

        self.assertEqual(expected_state_calls_sorted, actual_state_calls_sorted)

    @patch('cc_common.email_service_client.EmailServiceClient.send_privilege_investigation_state_notification_email')
    @patch('cc_common.email_service_client.EmailServiceClient.send_privilege_investigation_provider_notification_email')
    def test_privilege_investigation_listener_processes_event_with_registered_provider(
        self, mock_provider_email, mock_state_email
    ):
        """Test that privilege investigation listener processes events for registered providers."""
        from cc_common.email_service_client import InvestigationNotificationTemplateVariables
        from handlers.investigation_events import privilege_investigation_notification_listener

        # Set up test data with registered provider
        self.test_data_generator.put_default_provider_record_in_provider_table(
            value_overrides={'compactConnectRegisteredEmailAddress': 'provider@example.com'}
        )

        # Add the privilege that is under investigation
        self.test_data_generator.put_default_privilege_record_in_provider_table()

        # Create additional licenses and privileges for notification testing
        self.test_data_generator.put_default_license_record_in_provider_table(
            value_overrides={
                'jurisdiction': 'co',
                'jurisdictionUploadedLicenseStatus': 'active',
            }
        )
        self.test_data_generator.put_default_privilege_record_in_provider_table(
            value_overrides={
                'jurisdiction': 'ky',
                'administratorSetStatus': 'active',
            }
        )

        message = self._generate_privilege_investigation_message()
        event = self._create_sqs_event(message)

        # Execute the handler
        result = privilege_investigation_notification_listener(event, self.mock_context)

        # Should succeed with no batch failures
        self.assertEqual({'batchItemFailures': []}, result)

        # Verify provider notification
        mock_provider_email.assert_called_once_with(
            compact=DEFAULT_COMPACT,
            provider_email='provider@example.com',
            template_variables=InvestigationNotificationTemplateVariables(
                provider_first_name='Björk',
                provider_last_name='Guðmundsdóttir',
                investigation_jurisdiction=DEFAULT_PRIVILEGE_JURISDICTION,
                license_type='speech-language pathologist',
                provider_id=None,
            ),
        )

        # Verify state notifications (investigation state + other states with active licenses/privileges)
        expected_template_variables_ne = InvestigationNotificationTemplateVariables(
            provider_first_name='Björk',
            provider_last_name='Guðmundsdóttir',
            investigation_jurisdiction=DEFAULT_PRIVILEGE_JURISDICTION,
            license_type='speech-language pathologist',
            provider_id=UUID(DEFAULT_PROVIDER_ID),
        )
        expected_template_variables_co = InvestigationNotificationTemplateVariables(
            provider_first_name='Björk',
            provider_last_name='Guðmundsdóttir',
            investigation_jurisdiction=DEFAULT_PRIVILEGE_JURISDICTION,
            license_type='speech-language pathologist',
            provider_id=UUID(DEFAULT_PROVIDER_ID),
        )
        expected_template_variables_ky = InvestigationNotificationTemplateVariables(
            provider_first_name='Björk',
            provider_last_name='Guðmundsdóttir',
            investigation_jurisdiction=DEFAULT_PRIVILEGE_JURISDICTION,
            license_type='speech-language pathologist',
            provider_id=UUID(DEFAULT_PROVIDER_ID),
        )
        expected_state_calls = [
            # State 'ne' (investigation jurisdiction)
            {
                'compact': DEFAULT_COMPACT,
                'jurisdiction': DEFAULT_PRIVILEGE_JURISDICTION,
                'template_variables': expected_template_variables_ne,
            },
            # State 'co' (active license jurisdiction)
            {
                'compact': DEFAULT_COMPACT,
                'jurisdiction': 'co',
                'template_variables': expected_template_variables_co,
            },
            # State 'ky' (active privilege jurisdiction)
            {
                'compact': DEFAULT_COMPACT,
                'jurisdiction': 'ky',
                'template_variables': expected_template_variables_ky,
            },
        ]

        # Verify all state notifications were sent
        self.assertEqual(3, mock_state_email.call_count)
        actual_state_calls = [call.kwargs for call in mock_state_email.call_args_list]

        # Sort both lists for comparison
        expected_state_calls_sorted = sorted(expected_state_calls, key=lambda x: x['jurisdiction'])
        actual_state_calls_sorted = sorted(actual_state_calls, key=lambda x: x['jurisdiction'])

        self.assertEqual(expected_state_calls_sorted, actual_state_calls_sorted)

    @patch(
        'cc_common.email_service_client.EmailServiceClient.send_privilege_investigation_closed_state_notification_email'
    )
    @patch(
        'cc_common.email_service_client.EmailServiceClient.send_privilege_investigation_closed_provider_notification_email'
    )
    def test_privilege_investigation_closed_listener_processes_event_with_registered_provider(
        self, mock_provider_email, mock_state_email
    ):
        """Test that privilege investigation closed listener processes events for registered providers."""
        from cc_common.email_service_client import InvestigationNotificationTemplateVariables
        from handlers.investigation_events import privilege_investigation_closed_notification_listener

        # Set up test data with registered provider
        self.test_data_generator.put_default_provider_record_in_provider_table(
            value_overrides={'compactConnectRegisteredEmailAddress': 'provider@example.com'}
        )

        # Add the privilege that was under investigation
        self.test_data_generator.put_default_privilege_record_in_provider_table()

        # Create additional licenses and privileges for notification testing
        self.test_data_generator.put_default_license_record_in_provider_table(
            value_overrides={
                'jurisdiction': 'co',
                'jurisdictionUploadedLicenseStatus': 'active',
            }
        )
        self.test_data_generator.put_default_privilege_record_in_provider_table(
            value_overrides={
                'jurisdiction': 'ky',
                'administratorSetStatus': 'active',
            }
        )

        message = self._generate_privilege_investigation_closed_message()
        event = self._create_sqs_event(message)

        # Execute the handler
        result = privilege_investigation_closed_notification_listener(event, self.mock_context)

        # Should succeed with no batch failures
        self.assertEqual({'batchItemFailures': []}, result)

        # Verify provider notification
        mock_provider_email.assert_called_once_with(
            compact=DEFAULT_COMPACT,
            provider_email='provider@example.com',
            template_variables=InvestigationNotificationTemplateVariables(
                provider_first_name='Björk',
                provider_last_name='Guðmundsdóttir',
                investigation_jurisdiction=DEFAULT_PRIVILEGE_JURISDICTION,
                license_type='speech-language pathologist',
                provider_id=None,
            ),
        )

        # Verify state notifications (investigation state + other states with active licenses/privileges)
        expected_template_variables_ne = InvestigationNotificationTemplateVariables(
            provider_first_name='Björk',
            provider_last_name='Guðmundsdóttir',
            investigation_jurisdiction=DEFAULT_PRIVILEGE_JURISDICTION,
            license_type='speech-language pathologist',
            provider_id=UUID(DEFAULT_PROVIDER_ID),
        )
        expected_template_variables_co = InvestigationNotificationTemplateVariables(
            provider_first_name='Björk',
            provider_last_name='Guðmundsdóttir',
            investigation_jurisdiction=DEFAULT_PRIVILEGE_JURISDICTION,
            license_type='speech-language pathologist',
            provider_id=UUID(DEFAULT_PROVIDER_ID),
        )
        expected_template_variables_ky = InvestigationNotificationTemplateVariables(
            provider_first_name='Björk',
            provider_last_name='Guðmundsdóttir',
            investigation_jurisdiction=DEFAULT_PRIVILEGE_JURISDICTION,
            license_type='speech-language pathologist',
            provider_id=UUID(DEFAULT_PROVIDER_ID),
        )
        expected_state_calls = [
            # State 'ne' (investigation jurisdiction)
            {
                'compact': DEFAULT_COMPACT,
                'jurisdiction': DEFAULT_PRIVILEGE_JURISDICTION,
                'template_variables': expected_template_variables_ne,
            },
            # State 'co' (active license jurisdiction)
            {
                'compact': DEFAULT_COMPACT,
                'jurisdiction': 'co',
                'template_variables': expected_template_variables_co,
            },
            # State 'ky' (active privilege jurisdiction)
            {
                'compact': DEFAULT_COMPACT,
                'jurisdiction': 'ky',
                'template_variables': expected_template_variables_ky,
            },
        ]

        # Verify all state notifications were sent
        self.assertEqual(3, mock_state_email.call_count)
        actual_state_calls = [call.kwargs for call in mock_state_email.call_args_list]

        # Sort both lists for comparison
        expected_state_calls_sorted = sorted(expected_state_calls, key=lambda x: x['jurisdiction'])
        actual_state_calls_sorted = sorted(actual_state_calls, key=lambda x: x['jurisdiction'])

        self.assertEqual(expected_state_calls_sorted, actual_state_calls_sorted)

    def test_license_investigation_listener_handles_missing_provider_records(self):
        """Test that license investigation listener handles missing provider records gracefully."""
        from handlers.investigation_events import license_investigation_notification_listener

        # Don't set up any test data - provider records will be missing
        message = self._generate_license_investigation_message()
        event = self._create_sqs_event(message)

        # SQS handler wrapper catches exceptions and returns batch item failures
        result = license_investigation_notification_listener(event, self.mock_context)

        # Should return batch item failure for the message
        self.assertEqual(result['batchItemFailures'][0]['itemIdentifier'], '123')

    def test_privilege_investigation_listener_handles_missing_provider_records(self):
        """Test that privilege investigation listener handles missing provider records gracefully."""
        from handlers.investigation_events import privilege_investigation_notification_listener

        # Don't set up any test data - provider records will be missing
        message = self._generate_privilege_investigation_message()
        event = self._create_sqs_event(message)

        # SQS handler wrapper catches exceptions and returns batch item failures
        result = privilege_investigation_notification_listener(event, self.mock_context)

        # Should return batch item failure for the message
        self.assertEqual(result['batchItemFailures'][0]['itemIdentifier'], '123')

    @patch('cc_common.email_service_client.EmailServiceClient.send_license_investigation_provider_notification_email')
    def test_license_investigation_listener_handles_email_service_failure(self, mock_provider_email):
        """Test that license investigation listener handles email service failures gracefully."""
        from handlers.investigation_events import license_investigation_notification_listener

        # Set up test data
        self.test_data_generator.put_default_provider_record_in_provider_table(
            value_overrides={'compactConnectRegisteredEmailAddress': 'provider@example.com'}
        )
        self.test_data_generator.put_default_license_record_in_provider_table()

        # Make the email service raise an exception
        mock_provider_email.side_effect = Exception('Email service failure')

        message = self._generate_license_investigation_message()
        event = self._create_sqs_event(message)

        # SQS handler wrapper catches exceptions and returns batch item failures
        result = license_investigation_notification_listener(event, self.mock_context)

        # Should return batch item failure for the message
        self.assertEqual(result['batchItemFailures'][0]['itemIdentifier'], '123')

    @patch('cc_common.email_service_client.EmailServiceClient.send_privilege_investigation_provider_notification_email')
    def test_privilege_investigation_listener_handles_email_service_failure(self, mock_provider_email):
        """Test that privilege investigation listener handles email service failures gracefully."""
        from handlers.investigation_events import privilege_investigation_notification_listener

        # Set up test data
        self.test_data_generator.put_default_provider_record_in_provider_table(
            value_overrides={'compactConnectRegisteredEmailAddress': 'provider@example.com'}
        )
        self.test_data_generator.put_default_privilege_record_in_provider_table()

        # Make the email service raise an exception
        mock_provider_email.side_effect = Exception('Email service failure')

        message = self._generate_privilege_investigation_message()
        event = self._create_sqs_event(message)

        # SQS handler wrapper catches exceptions and returns batch item failures
        result = privilege_investigation_notification_listener(event, self.mock_context)

        # Should return batch item failure for the message
        self.assertEqual(result['batchItemFailures'][0]['itemIdentifier'], '123')
