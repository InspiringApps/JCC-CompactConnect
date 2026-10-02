# Temporary cross-stack exports

These exports are kept so a deploy can update the stacks that import them before the exports are deleted. CloudFormation updates the producing stack first and cancels the deploy if an export is still imported.

Do not remove a row's resources until every stack in its "Blocked by" column has a deployed template that no longer imports the export.

## Delete after the next successful test deploy

This deploy leaves the exports in place and removes the imports from Test-APIStack, because those routes are no longer in the CDK app. After that deploy finishes, delete the dummy functions and their `export_value` calls in `stacks/api_lambda_stack/__init__.py`.

| Export | Producing stack | Resource | Blocked by |
| --- | --- | --- | --- |
| `ExportsOutputFnGetAttAttestationsFunction14537685Arn44A24BA0` | ApiLambdaStack | `AttestationsFunction` | Test-APIStack |
| `ExportsOutputFnGetAttPostPurchasePrivilegesHandler439A8988Arn30F43AF7` | ApiLambdaStack | `PostPurchasePrivilegesHandler` | Test-APIStack |
| `ExportsOutputFnGetAttGetPurchasePrivilegeOptionsHandler5EA95AF5Arn17A30A54` | ApiLambdaStack | `GetPurchasePrivilegeOptionsHandler` | Test-APIStack |
| `ExportsOutputFnGetAttV1BulkUrlHandler3DA7690CArn6FED5D87` | ApiLambdaStack | `V1BulkUrlHandler` | Test-APIStack |
| `ExportsOutputFnGetAttMilitaryAuditHandlerE3C48C36ArnA9AEB6F2` | ApiLambdaStack | `MilitaryAuditHandler` | Test-APIStack |
| `ExportsOutputFnGetAttDeactivatePrivilegeHandler50A25446Arn240F0B9F` | ApiLambdaStack | `DeactivatePrivilegeHandler` | Test-APIStack |
| `ExportsOutputFnGetAttGetPrivilegeHistory60AB0634ArnD4E26DC9` | ApiLambdaStack | `GetPrivilegeHistory` | Test-APIStack |
| `ExportsOutputFnGetAttProviderRegistrationHandler27C4CD127Arn3DCE0349` | ApiLambdaStack | `ProviderRegistrationHandler2` | Test-APIStack |
| `ExportsOutputFnGetAttProviderRegistrationHandler498BC1AEArn3AF431AE` | ApiLambdaStack | `ProviderRegistrationHandler` dummy in `provider_users.py` | Test-APIStack |
| `ExportsOutputFnGetAttProviderRegistrationHandlerLogRetentionB1FF4555LogGroupNameA8F05A47` | ApiLambdaStack | `ProviderRegistrationHandler` log group | Test-APIStack |

These are every function ARN the original API stack imported that the current API no longer references. The functions the current API still calls keep their exports automatically: compact configuration, credentials, feature flags, provider query/get/SSN, encumbrance, investigation, provider users me, home jurisdiction, account recovery, public lookup, and staff users.

## Delete only after the stack is removed outside the pipeline

CDK does not delete a stack that was removed from the pipeline stage. Delete the stack in CloudFormation first, then remove the resources and `export_value` calls.

### Test-StateAPIStack

Producing stack: PersistentStack (`stacks/persistent_stack/__init__.py` `_retain_license_upload_exports`, plus the bucket, license upload role, ingest role, and license preprocessing queue).

| Export |
| --- |
| `ExportsOutputRefBulkUploadsBucketDA4BDCD0B88AD67A` |
| `ExportsOutputFnGetAttBulkUploadsBucketDA4BDCD0Arn3AC64FAA` |
| `ExportsOutputFnGetAttSSNTableLicenseUploadRole46F85F47Arn4FD0FC20` |
| `ExportsOutputRefSSNTableLicenseQueuePreprocessorQueue6FC547AEED90D69B` |
| `ExportsOutputFnGetAttSSNTableLicenseQueuePreprocessorQueue6FC547AEArn1F1BB89A` |

Test-ApiLambdaStack also imported the bucket. Its bulk-upload handler no longer references the bucket, so that import drops in the same deploy that keeps the export. StateAPIStack is the remaining importer.

### Test-ExpirationReminderStack

Producing stack: SearchPersistentStack.

| Export |
| --- |
| `ExportsOutputFnGetAttProviderSearchDomainBE95F501DomainEndpointEA6672FC` |
| `ExportsOutputFnGetAttProviderSearchDomainBE95F501Arn22F09C87` |

## Order

1. Deploy this revision. It keeps every export above.
2. After that deploy succeeds, remove the ApiLambdaStack dummies in the first table.
3. Delete Test-StateAPIStack, then remove the PersistentStack license-upload resources and exports.
4. Delete Test-ExpirationReminderStack, then remove the SearchPersistentStack domain endpoint and ARN exports.

Steps 2, 3, and 4 are independent of each other. Do not combine a step with the deploy that still needs its export.
