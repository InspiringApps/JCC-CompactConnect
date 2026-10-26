# Temporary cross-stack exports

These exports are kept so a deploy can update the stacks that import them before the exports are deleted. CloudFormation updates the producing stack first and cancels the deploy if an export is still imported.

The API lambda placeholders from the first removal list are gone. Test-APIStack no longer imports them.

Do not remove a row's resources until the stack that still imports the export has been deleted. CDK does not delete a stack that was removed from the pipeline stage. Delete the stack in CloudFormation first, then remove the resources and `export_value` calls.

## Test-StateAPIStack

Producing stack: PersistentStack (`stacks/persistent_stack/__init__.py` `_retain_license_upload_exports`, plus the bucket, license upload role, ingest role, and license preprocessing queue).

| Export |
| --- |
| `ExportsOutputRefBulkUploadsBucketDA4BDCD0B88AD67A` |
| `ExportsOutputFnGetAttBulkUploadsBucketDA4BDCD0Arn3AC64FAA` |
| `ExportsOutputFnGetAttSSNTableLicenseUploadRole46F85F47Arn4FD0FC20` |
| `ExportsOutputRefSSNTableLicenseQueuePreprocessorQueue6FC547AEED90D69B` |
| `ExportsOutputFnGetAttSSNTableLicenseQueuePreprocessorQueue6FC547AEArn1F1BB89A` |

Test-ApiLambdaStack also imported the bucket. Its bulk-upload handler no longer references the bucket, so that import is already gone. StateAPIStack is the remaining importer.

## Test-ExpirationReminderStack

Producing stack: SearchPersistentStack.

| Export |
| --- |
| `ExportsOutputFnGetAttProviderSearchDomainBE95F501DomainEndpointEA6672FC` |
| `ExportsOutputFnGetAttProviderSearchDomainBE95F501Arn22F09C87` |

## Order

1. Delete Test-StateAPIStack, then remove the PersistentStack license-upload resources and exports.
2. Delete Test-ExpirationReminderStack, then remove the SearchPersistentStack domain endpoint and ARN exports.

These steps are independent of each other. Do not remove an export in the same deploy that still needs it.

Public lookup lambda ARN exports stay. Test still wires those routes, and beta does not, so the explicit exports avoid a deadly embrace between those environments.
