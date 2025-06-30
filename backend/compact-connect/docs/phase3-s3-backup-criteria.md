# Phase 3 S3 Backup Implementation - Bucket Inclusion Criteria

This document describes the criteria used to determine which S3 buckets are included in or excluded from backup protection as part of Phase 3 of the data retention implementation plan.

## Backup Inclusion Criteria

According to Phase 3 specifications, S3 buckets are included in backup protection if they contain:

1. **Primary provider data** - Irreplaceable data uploaded by or about providers
2. **Uploaded documents** - Files that cannot be easily regenerated
3. **Irreplaceable information** - Data that would result in data loss if destroyed

## Backup Exclusion Criteria

S3 buckets are excluded from backup protection if they contain:

1. **Transitory data** - Temporary files during processing workflows
2. **Derived reports** - Files that can be regenerated from primary data sources
3. **Cache data** - Files used for performance optimization that can be recreated
4. **Processing artifacts** - Intermediate files created during data processing

## Bucket Classification

### Included in Backup (Phase 3)

#### ProviderUsersBucket
- **Category**: `document_storage`
- **Retention**: 90 days
- **Justification**: Contains primary provider documents such as military affiliation records and other irreplaceable provider data
- **Backup Schedule**: Daily at 2 AM UTC
- **Cross-Account Replication**: Yes

### Excluded from Backup (Phase 3)

#### BulkUploadsBucket
- **Reason**: Contains transitory data only during the bulk upload processing workflow
- **Data Type**: Temporary CSV files that are processed and then deleted
- **Retention**: Files are deleted after processing
- **Justification**: No backup needed as data is temporary and processing can be retried
- **NAG Suppression**: "This bucket houses transitory data only, so replication to a backup bucket is unhelpful"

#### TransactionReportsBucket
- **Reason**: Contains derived reports that can be regenerated from primary data sources
- **Data Type**: Read-only transaction reports generated from transaction history data
- **Regeneration**: Reports can be recreated from transaction_history_table data
- **Justification**: Backup not required as reports are derived data, not primary data
- **NAG Suppression**: "This bucket is used to store read-only reports that can be regenerated as needed"

## Implementation Details

### Backup Configuration

Buckets included in backup use the `BackupPlanConstruct` with the following configuration:

```python
self.backup_plan = BackupPlanConstruct(
    self,
    'BackupPlan',
    resource_arn=self.bucket_arn,
    backup_category='document_storage',
    local_backup_vault=backup_infra.backup_vault,
    backup_service_role=backup_infra.backup_service_role,
    cross_account_vault_arn=backup_infra.cross_account_vault_arn,
)
```

### Backup Categories

- **document_storage**: For primary provider documents and irreplaceable files
  - Schedule: Daily at 2 AM UTC (`cron(0 2 * * ? *)`)
  - Retention: 90 days
  - Cross-account replication: Enabled

### Cross-Account Replication

All backed-up S3 buckets include cross-account replication to a backup account in `us-west-2` region for geographic separation and disaster recovery capability.

## Future Considerations

### Buckets to Evaluate in Future Phases

As new buckets are added to the system, they should be evaluated against the inclusion criteria:

1. **AccessLogsBucket**: Currently used for S3 access logs - may need evaluation if log retention requirements change
2. **Future provider data buckets**: Any new buckets containing provider documents should use `document_storage` category
3. **Configuration data buckets**: May need `configuration_data` category with longer retention

### Lifecycle Management

The transaction reports bucket has a TODO comment indicating future lifecycle policy implementation. When this is implemented, consider whether lifecycle-managed derived data needs backup protection.

## Testing

Phase 3 implementation includes comprehensive tests:

1. **Unit tests**: `test_backup_plan.py` - Tests backup plan construct functionality
2. **Infrastructure tests**: `test_backup_infrastructure_stack.py` - Tests backup infrastructure
3. **Integration tests**: `test_provider_users_bucket_backup.py` - Tests S3 bucket backup integration
4. **Exclusion verification**: Tests confirm excluded buckets do not implement backup

## Monitoring

All backup operations are monitored through AWS Backup service metrics and will be enhanced in Phase 5 with custom monitoring and alerting.