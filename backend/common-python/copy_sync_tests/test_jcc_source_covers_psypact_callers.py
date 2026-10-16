"""JCC source modules must expose every method/type selected PSYPACT handlers call.

These tests read Cosmetology/JCC source files (not the copies) so a superficially similar
JCC class cannot replace a Cosmetology one unless it actually covers the PSYPACT call surface.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from copy_sync_tests.copied_file_text import REPO_ROOT

_COSMO_COMMON = REPO_ROOT / 'backend/cosmetology-app/lambdas/python/common/cc_common'
_JCC_COMMON = REPO_ROOT / 'backend/compact-connect/lambdas/python/common/cc_common'

# Methods copied Cosmetology + JCC handlers invoke on config.email_service_client.
_PSYPACT_EMAIL_METHODS = frozenset(
    {
        'send_privilege_encumbrance_state_notification_email',
        'send_privilege_encumbrance_lifting_state_notification_email',
        'send_license_encumbrance_state_notification_email',
        'send_license_encumbrance_lifting_state_notification_email',
        'send_license_investigation_state_notification_email',
        'send_license_investigation_closed_state_notification_email',
        'send_privilege_investigation_state_notification_email',
        'send_privilege_investigation_closed_state_notification_email',
        'send_compact_transaction_report_email',
        'send_jurisdiction_transaction_report_email',
        'send_provider_email_verification_code',
        'send_provider_email_change_notification',
        'send_provider_account_recovery_confirmation_email',
        'send_home_jurisdiction_change_old_state_notification',
        'send_home_jurisdiction_change_new_state_notification',
    }
)
_PSYPACT_EMAIL_DATACLASSES = frozenset(
    {
        'EncumbranceNotificationTemplateVariables',
        'InvestigationNotificationTemplateVariables',
    }
)

_PSYPACT_EVENT_BUS_METHODS = frozenset(
    {
        '_publish_event',
        'publish_investigation_event',
        'publish_investigation_closed_event',
        'publish_privilege_encumbrance_event',
        'publish_license_encumbrance_event',
        'publish_privilege_encumbrance_lifting_event',
        'publish_license_encumbrance_lifting_event',
        'publish_home_jurisdiction_change_event',
    }
)

_PSYPACT_COMPACT_CONFIG_METHODS = frozenset(
    {
        'get_compact_configuration',
        'save_compact_configuration',
        'get_active_compact_jurisdictions',
        'get_live_compact_jurisdictions',
        'get_jurisdiction_configuration',
        'save_jurisdiction_configuration',
        'set_compact_authorize_net_public_values',
        'get_privilege_purchase_options',
        'get_jurisdiction_operations_team_emails',
    }
)

_PSYPACT_DATA_CLIENT_JCC_METHODS = frozenset(
    {
        'update_provider_home_state_jurisdiction',
        'create_military_affiliation',
        'end_military_affiliation',
        'update_provider_email_verification_data',
        'clear_provider_email_verification_data',
        'complete_provider_email_update',
        'update_provider_account_recovery_data',
        'clear_provider_account_recovery_data',
        'get_privilege_for_transaction_id',
    }
)


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding='utf-8'))


def _class_def(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f'class {name} not found')


def _method_names(class_def: ast.ClassDef) -> set[str]:
    return {node.name for node in class_def.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _top_level_class_names(tree: ast.Module) -> set[str]:
    return {node.name for node in tree.body if isinstance(node, ast.ClassDef)}


def _assignment_names(class_def: ast.ClassDef) -> set[str]:
    names: set[str] = set()
    for node in class_def.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


class TestJccSourceCoversPsypactCallers(unittest.TestCase):
    def test_jcc_email_client_covers_selected_callers(self):
        jcc = _parse(_JCC_COMMON / 'email_service_client.py')
        methods = _method_names(_class_def(jcc, 'EmailServiceClient'))
        missing = sorted(_PSYPACT_EMAIL_METHODS - methods)
        self.assertEqual(missing, [], 'JCC EmailServiceClient is missing PSYPACT-selected email methods.')
        dataclasses = _top_level_class_names(jcc)
        missing_dc = sorted(_PSYPACT_EMAIL_DATACLASSES - dataclasses)
        self.assertEqual(missing_dc, [], 'JCC email_service_client.py is missing PSYPACT email dataclasses.')

    def test_jcc_event_bus_covers_selected_callers(self):
        jcc = _parse(_JCC_COMMON / 'event_bus_client.py')
        methods = _method_names(_class_def(jcc, 'EventBusClient'))
        missing = sorted(_PSYPACT_EVENT_BUS_METHODS - methods)
        self.assertEqual(missing, [], 'JCC EventBusClient is missing PSYPACT-selected publish methods.')

    def test_jcc_compact_configuration_client_covers_selected_callers(self):
        jcc = _parse(_JCC_COMMON / 'data_model/compact_configuration_client.py')
        methods = _method_names(_class_def(jcc, 'CompactConfigurationClient'))
        missing = sorted(_PSYPACT_COMPACT_CONFIG_METHODS - methods)
        self.assertEqual(missing, [], 'JCC CompactConfigurationClient is missing PSYPACT-selected methods.')

    def test_jcc_data_client_has_account_methods_psypact_calls(self):
        jcc = _parse(_JCC_COMMON / 'data_model/data_client.py')
        methods = _method_names(_class_def(jcc, 'DataClient'))
        missing = sorted(_PSYPACT_DATA_CLIENT_JCC_METHODS - methods)
        self.assertEqual(missing, [], 'JCC DataClient is missing PSYPACT-selected account methods.')

    def test_cosmo_configured_state_schema_is_subset_of_jcc_compact_common(self):
        cosmo = _parse(_COSMO_COMMON / 'data_model/schema/compact/common.py')
        jcc = _parse(_JCC_COMMON / 'data_model/schema/compact/common.py')
        cosmo_fields = _assignment_names(_class_def(cosmo, 'ConfiguredStateSchema'))
        jcc_fields = _assignment_names(_class_def(jcc, 'ConfiguredStateSchema'))
        missing = sorted(cosmo_fields - jcc_fields)
        self.assertEqual(missing, [], 'JCC ConfiguredStateSchema dropped Cosmetology compact-config fields.')
        self.assertIn('PaymentProcessorPublicFieldsSchema', _top_level_class_names(jcc))

    def test_cosmo_encumbrance_event_schema_is_subset_of_jcc(self):
        cosmo = _parse(_COSMO_COMMON / 'data_model/schema/data_event/api.py')
        jcc = _parse(_JCC_COMMON / 'data_model/schema/data_event/api.py')
        for class_name in (
            'EncumbranceEventDetailSchema',
            'InvestigationEventDetailSchema',
            'LicenseDeactivationDetailSchema',
            'LicenseRevertDetailSchema',
        ):
            missing = sorted(
                _assignment_names(_class_def(cosmo, class_name)) - _assignment_names(_class_def(jcc, class_name))
            )
            self.assertEqual(missing, [], f'JCC {class_name} dropped Cosmetology event fields.')
        self.assertIn('HomeJurisdictionChangeEventDetailSchema', _top_level_class_names(jcc))

    def test_cosmo_provider_record_fields_are_subset_of_jcc(self):
        cosmo = _parse(_COSMO_COMMON / 'data_model/schema/provider/record.py')
        jcc = _parse(_JCC_COMMON / 'data_model/schema/provider/record.py')
        missing = sorted(
            _assignment_names(_class_def(cosmo, 'ProviderRecordSchema'))
            - _assignment_names(_class_def(jcc, 'ProviderRecordSchema'))
        )
        self.assertEqual(missing, [], 'JCC ProviderRecordSchema dropped Cosmetology provider fields.')
        jcc_fields = _assignment_names(_class_def(jcc, 'ProviderRecordSchema'))
        self.assertIn('currentHomeJurisdiction', jcc_fields)
        self.assertIn('pendingEmailAddress', jcc_fields)
        self.assertIn('militaryStatus', jcc_fields)

    def test_jcc_provider_record_eligibility_is_not_cosmo_compatible(self):
        """JCC compactEligibility requires currentHomeJurisdiction; Cosmetology fixtures omit it."""
        cosmo = (_COSMO_COMMON / 'data_model/schema/provider/record.py').read_text(encoding='utf-8')
        jcc = (_JCC_COMMON / 'data_model/schema/provider/record.py').read_text(encoding='utf-8')
        self.assertNotIn('currentHomeJurisdiction', cosmo)
        self.assertIn(
            "in_data.get('currentHomeJurisdiction', UNKNOWN_JURISDICTION) == in_data['licenseJurisdiction']",
            jcc,
        )
