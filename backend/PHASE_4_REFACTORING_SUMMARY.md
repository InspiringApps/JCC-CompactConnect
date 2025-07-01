# Phase 4 Cognito Backup Refactoring Summary

This document summarizes the completed refactoring of the Phase 4 Cognito backup implementation as requested.

## Changes Made

### 1. Created New Common Construct

**File**: `backend/compact-connect/common_constructs/cognito_user_backup.py`

Created a reusable common construct `CognitoUserBackup` that packages all resources needed for backing up a single Cognito user pool:

- **S3 Bucket**: For storing exported user data with versioning and KMS encryption
- **Lambda Function**: For exporting user data from Cognito to S3
- **EventBridge Rule**: For daily scheduling (2 AM UTC) with event parameters
- **Backup Plan**: Using `CCBackupPlan` for cross-account replication
- **CloudWatch Alarm**: For monitoring backup failures

The construct takes the following parameters:
- `user_pool_id`: The specific user pool to backup
- `user_pool_type`: Either 'staff' or 'provider' for organization
- `access_logs_bucket`: Shared access logs bucket
- `encryption_key`: KMS key for encryption
- `removal_policy`: Stack removal policy
- `backup_infrastructure_stack`: Reference to backup infrastructure
- `environment_context`: Environment configuration
- `alarm_topic`: SNS topic for alerts

### 2. Updated User Pool Constructs

**Files Modified**:
- `backend/compact-connect/stacks/persistent_stack/staff_users.py`
- `backend/compact-connect/stacks/persistent_stack/provider_users.py`
- `backend/compact-connect/stacks/provider_users/provider_users.py`

Each user pool construct now includes the `CognitoUserBackup` construct:

```python
self.backup_system = CognitoUserBackup(
    self,
    'UserPoolBackup',
    user_pool_id=self.user_pool_id,
    user_pool_type='staff',  # or 'provider'
    access_logs_bucket=stack.access_logs_bucket,
    encryption_key=encryption_key,
    removal_policy=removal_policy,
    backup_infrastructure_stack=backup_infrastructure_stack,
    environment_context=environment_context,
    alarm_topic=stack.alarm_topic,
)
```

### 3. Enhanced EventBridge Integration

The EventBridge rule now passes specific parameters to the Lambda function:

```json
{
    "user_pool_id": "us-east-1_xxxxxxxxx",
    "backup_bucket_name": "bucket-name",
    "user_pool_type": "staff"
}
```

This allows a single Lambda function to handle any user pool based on the event parameters.

### 4. Removed Centralized Implementation

**File**: `backend/compact-connect/stacks/backup_infrastructure_stack.py`

Removed the old centralized approach:
- Deleted `_create_cognito_backup_system()` method
- Removed `set_user_pool_ids()` method
- Cleaned up unused imports and parameters
- Removed the old `CognitoBackupBucket` construct file

### 5. Updated Dependency Management

**Files Modified**:
- `backend/bin/compile_requirements.sh`
- `backend/bin/sync_deps.sh`

Added cognito-backup lambda to both dependency compilation and synchronization scripts:

```bash
pip-compile --no-emit-index-url --upgrade --no-strip-extras compact-connect/lambdas/python/cognito-backup/requirements-dev.in
pip-compile --no-emit-index-url --upgrade --no-strip-extras compact-connect/lambdas/python/cognito-backup/requirements.in
```

**New Files Created**:
- `backend/compact-connect/lambdas/python/cognito-backup/requirements.in`
- `backend/compact-connect/lambdas/python/cognito-backup/requirements-dev.in`

### 6. Updated Tests

**Files Modified**:
- `backend/compact-connect/tests/app/test_cognito_backup.py`
- `backend/compact-connect/lambdas/python/cognito-backup/tests/test_lambda_function.py`

Updated all tests to reflect the new distributed architecture:

- Tests now check for backup systems on individual user pools instead of centralized infrastructure
- Updated expected resource counts (now 2+ buckets, lambdas, rules, etc.)
- Modified Lambda function tests to use the new constructor signature
- Updated event structure tests to check for event parameters instead of environment variables

### 7. Lambda Function Updates

The existing Lambda function (`lambda_function.py`) was already correctly implemented to use event parameters, so no changes were needed there.

## Architecture Benefits

The refactored architecture provides several advantages:

1. **Modularity**: Each user pool manages its own backup system
2. **Scalability**: Easy to add backup for new user pools
3. **Maintainability**: Clear separation of concerns
4. **Reusability**: Common construct can be used by any user pool
5. **Flexibility**: EventBridge parameters allow single Lambda to handle multiple pools

## Event Flow

1. EventBridge rule triggers daily at 2 AM UTC
2. Rule passes specific parameters (user_pool_id, bucket_name, user_pool_type) to Lambda
3. Lambda exports users from the specified pool to the specified bucket
4. CCBackupPlan automatically backs up the S3 bucket to cross-account vault
5. CloudWatch alarm monitors for failures and alerts via SNS

## File Structure

```
backend/compact-connect/
├── common_constructs/
│   ├── cognito_user_backup.py          # New common construct
│   └── backup_plan.py                  # Existing backup plan construct
├── stacks/
│   ├── persistent_stack/
│   │   ├── staff_users.py              # Updated with backup system
│   │   └── provider_users.py           # Updated with backup system
│   ├── provider_users/
│   │   └── provider_users.py           # Updated with backup system
│   └── backup_infrastructure_stack.py  # Cleaned up, removed old methods
├── lambdas/python/cognito-backup/
│   ├── lambda_function.py              # Unchanged (already correct)
│   ├── requirements.in                 # New
│   ├── requirements-dev.in             # New
│   └── tests/
│       └── test_lambda_function.py     # Updated for new architecture
└── tests/app/
    └── test_cognito_backup.py          # Updated for new architecture
```

## Next Steps

1. Install dependencies (`pip-tools` and `ruff`) to compile requirements and format code
2. Run dependency compilation: `backend/bin/compile_requirements.sh`
3. Format code: `backend/bin/format_python.sh`
4. Run tests to validate the implementation
5. Deploy to test environment for integration testing

## Summary

The refactoring successfully moves from a centralized Cognito backup approach to a distributed, modular approach where each user pool manages its own backup system through a common construct. This aligns with the existing patterns in the codebase where individual resources manage their own backup plans using shared infrastructure.