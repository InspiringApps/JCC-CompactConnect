# Features PSYPACT preserves from other projects

PSYPACT runtime Python lives in `backend/common-python`. Copied files begin with `# Copied from` or `# Copied method bodies from`. Those comments name the source file. Imports are rewritten from `cc_common` to `common_lambdas`. `copy_sync_tests` checks that each copy still matches its source after that rewrite.

Two source apps supply the copied code:

- **Cosmetology** (`backend/cosmetology-app`) is the provider model. Privileges are generated when a provider is read, from the home license plus privilege encumbrances and investigations. Privilege and privilege-update records are not stored.
- **Compact Connect** (`backend/compact-connect`), the JCC app, supplies practitioner login, attestations, and the Authorize.Net client. Selected JCC data-client methods are mixed onto the Cosmetology data client.

`PsypactDataClient` is the composition of those two: Cosmetology `DataClient` plus `JccDataClientMixin`. It is defined in `backend/psypact-app/lambdas/python/common/cc_common/psypact_data_client.py`.

## Practitioner account

Copied from Compact Connect so a practitioner can register, sign in, and maintain their own record.

| Feature | Where it runs | Source |
| --- | --- | --- |
| Registration, profile, email change | `backend/common-python/lambdas/provider-data-v1/handlers/provider_users.py` | `backend/compact-connect/lambdas/python/provider-data-v1/handlers/provider_users.py` |
| Account recovery | `backend/common-python/lambdas/provider-data-v1/handlers/account_recovery.py` | `backend/compact-connect/lambdas/python/provider-data-v1/handlers/account_recovery.py` |
| Home-jurisdiction change events | `backend/common-python/lambdas/data-events/handlers/home_jurisdiction_events.py` | `backend/compact-connect/lambdas/python/data-events/handlers/home_jurisdiction_events.py` |
| Email delivery | `common_lambdas/email_service_client.py` | `backend/compact-connect/lambdas/python/common/cc_common/email_service_client.py` |
| Practitioner and military schemas | `common_lambdas/data_model/schema/provider/jcc_provider*.py`, `common_lambdas/data_model/schema/military_affiliation/` | `backend/compact-connect/lambdas/python/common/cc_common/data_model/schema/provider/` and `schema/military_affiliation/` |

`lambdas/python/common/cc_common/psypact_home_jurisdiction.py` is PSYPACT-specific. The `put_home_jurisdiction.py` Lambda entry calls it. It calls the shared home-jurisdiction writer and rejects a change unless the selected jurisdiction has an unexpired, compact-eligible license.

Method bodies copied from Compact Connect `data_client.py` into `common_lambdas/data_model/jcc_data_client_mixin.py`:

- `update_provider_home_state_jurisdiction`
- `create_military_affiliation` and `end_military_affiliation`
- `update_provider_email_verification_data`, `clear_provider_email_verification_data`, and `complete_provider_email_update`
- `update_provider_account_recovery_data` and `clear_provider_account_recovery_data`
- `get_privilege_for_transaction_id`, plus the private helpers those methods call

## Attestations

Practitioners can read the attestation text they agree to.

| Where it runs | Source |
| --- | --- |
| `backend/common-python/lambdas/compact-configuration/handlers/attestations.py` | `backend/compact-connect/lambdas/python/compact-configuration/handlers/attestations.py` |
| `common_lambdas/data_model/schema/attestation/` | `backend/compact-connect/lambdas/python/common/cc_common/data_model/schema/attestation/` |
| `common_lambdas/data_model/compact_configuration_client.py` | `backend/compact-connect/lambdas/python/common/cc_common/data_model/compact_configuration_client.py` |

The route is `GET /v1/compacts/{compact}/attestations/{attestationId}`.

## Authorize.Net

The payment client is copied so a later application-submission flow can charge a card. The privilege-purchase routes (`POST /v1/purchases/privileges` and the purchase-options route) are not wired.

| Where it runs | Source |
| --- | --- |
| `backend/common-python/lambdas/purchases/purchase_client.py` | `backend/compact-connect/lambdas/python/purchases/purchase_client.py` |
| `backend/common-python/lambdas/purchases/handlers/credentials.py` | `backend/compact-connect/lambdas/python/purchases/handlers/credentials.py` |
| `backend/common-python/lambdas/purchases/handlers/transaction_history.py` | `backend/compact-connect/lambdas/python/purchases/handlers/transaction_history.py` |
| `backend/common-python/lambdas/purchases/handlers/transaction_reporting.py` | `backend/compact-connect/lambdas/python/purchases/handlers/transaction_reporting.py` |
| `backend/common-python/lambdas/purchases/report_window.py` | `backend/compact-connect/lambdas/python/purchases/report_window.py` |
| `common_lambdas/data_model/transaction_client.py` | `backend/compact-connect/lambdas/python/common/cc_common/data_model/transaction_client.py` |
| `common_lambdas/data_model/schema/purchase/` and `schema/transaction/` | `backend/compact-connect/lambdas/python/common/cc_common/data_model/schema/purchase/` and `schema/transaction/` |

## Provider records, generated privileges, and public lookup

Copied from Cosmetology. A privilege exists for a jurisdiction when the home license is compact-eligible and no unlifted privilege encumbrance blocks it. Staff do not deactivate a single stored privilege, and there is no privilege-history record.

| Feature | PSYPACT file | Source |
| --- | --- | --- |
| Provider read and write | `lambdas/python/provider-data-v1/handlers/providers.py` | `backend/cosmetology-app/lambdas/python/provider-data-v1/handlers/providers.py` |
| Public provider lookup | `lambdas/python/provider-data-v1/handlers/public_lookup.py` | `backend/cosmetology-app/lambdas/python/provider-data-v1/handlers/public_lookup.py` |
| Privilege generation | `common_lambdas/data_model/provider_record_util.py` | `backend/cosmetology-app/lambdas/python/common/cc_common/data_model/provider_record_util.py` |
| Provider data access | `common_lambdas/data_model/data_client.py` | `backend/cosmetology-app/lambdas/python/common/cc_common/data_model/data_client.py` |
| License, privilege, and provider schemas | `common_lambdas/data_model/schema/license/`, `schema/privilege/`, `schema/provider/` | the matching paths under `backend/cosmetology-app/lambdas/python/common/cc_common/data_model/schema/` |

## Encumbrance and investigation

Copied from Cosmetology. These records are what can make a generated privilege inactive.

| PSYPACT file | Source |
| --- | --- |
| `lambdas/python/provider-data-v1/handlers/encumbrance.py` | `backend/cosmetology-app/lambdas/python/provider-data-v1/handlers/encumbrance.py` |
| `lambdas/python/provider-data-v1/handlers/investigation.py` | `backend/cosmetology-app/lambdas/python/provider-data-v1/handlers/investigation.py` |
| `lambdas/python/data-events/handlers/encumbrance_events.py` | `backend/cosmetology-app/lambdas/python/data-events/handlers/encumbrance_events.py` |
| `lambdas/python/data-events/handlers/investigation_events.py` | `backend/cosmetology-app/lambdas/python/data-events/handlers/investigation_events.py` |
| `common_lambdas/data_model/schema/adverse_action/` and `schema/investigation/` | the matching Cosmetology schema directories |

## Staff users and search

Copied from Cosmetology.

| Feature | Where it runs | Source |
| --- | --- | --- |
| Staff user API | `lambdas/python/staff-users/handlers/users.py`. `me.py` is `backend/common-python/lambdas/staff-users/handlers/me.py` | `backend/cosmetology-app/lambdas/python/staff-users/handlers/` |
| Staff token claims | `lambdas/python/staff-user-pre-token/user_data.py`. `main.py` is `backend/common-python/lambdas/staff-user-pre-token/main.py` | `backend/cosmetology-app/lambdas/python/staff-user-pre-token/` |
| Staff provider search | `lambdas/python/search/handlers/search.py` | `backend/cosmetology-app/lambdas/python/search/handlers/search.py` |
| Public provider search | `backend/common-python/lambdas/search/handlers/public_search.py` | `backend/cosmetology-app/lambdas/python/search/handlers/public_search.py` |
| Search index updates | `lambdas/python/search/handlers/provider_update_ingest.py`, `populate_provider_documents.py`, `manage_opensearch_indices.py` | `backend/cosmetology-app/lambdas/python/search/handlers/` |

## Compact configuration, feature flags, and operations

Copied from Cosmetology, except the attestation handler listed above.

| Feature | Where it runs | Source |
| --- | --- | --- |
| Compact and jurisdiction configuration | `lambdas/python/compact-configuration/handlers/compact_configuration.py` | `backend/cosmetology-app/lambdas/python/compact-configuration/handlers/compact_configuration.py` |
| Configuration upload | `lambdas/python/custom-resources/handlers/compact_config_uploader.py` | `backend/cosmetology-app/lambdas/python/custom-resources/handlers/compact_config_uploader.py` |
| SES identity verification | `backend/common-python/lambdas/custom-resources/handlers/ses_email_identity_verification_handler.py` | `backend/cosmetology-app/lambdas/python/custom-resources/handlers/ses_email_identity_verification_handler.py` |
| Feature flags | `backend/common-python/lambdas/feature-flag/` | `backend/cosmetology-app/lambdas/python/feature-flag/` |
| Cognito user backup | `backend/common-python/lambdas/cognito-backup/handlers/cognito_backup.py` | `backend/cosmetology-app/lambdas/python/cognito-backup/handlers/cognito_backup.py` |
| Disaster-recovery copy and cleanup | `backend/common-python/lambdas/disaster-recovery/handlers/` | `backend/cosmetology-app/lambdas/python/disaster-recovery/handlers/` |
| Provider data-change events | `lambdas/python/data-events/handlers/data_events.py` | `backend/cosmetology-app/lambdas/python/data-events/handlers/data_events.py` |

Shared Cosmetology modules used by those handlers include `common_lambdas/config.py`, `exceptions.py`, `utils.py`, `feature_flag_client.py`, `license_util.py`, `signature_auth.py`, and `event_batch_writer.py`.

Compact Connect also contributes `common_lambdas/event_bus_client.py` and `common_lambdas/event_state_client.py`, from `backend/compact-connect/lambdas/python/common/cc_common/`.
