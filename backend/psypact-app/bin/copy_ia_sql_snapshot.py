#!/usr/bin/env python3
"""
Copy the PSY|PRO SQL Server snapshot into a destination account.

Run this once per destination environment before that environment's pipeline deploy.
The pipeline restores whatever snapshot id this script prints. It does not copy the
snapshot itself.

Production copy standard
------------------------
- The destination account does not get an IAM role in the source account. The snapshot
  is shared by adding the destination account id to the snapshot restore attribute.
- The source snapshot is unencrypted. RDS cannot turn encryption on when restoring, so
  the first copy encrypts it with a customer-managed key.
- The snapshot CloudFormation restores is owned by the destination account and encrypted
  with a customer-managed key in that account. Key rotation is enabled. After the copy
  finishes, the destination does not need the source key.
- The source key policy grants each destination account only kms:Decrypt, kms:DescribeKey,
  and kms:CreateGrant. RDS needs those three actions to copy an encrypted snapshot.
- Re-running for another environment reuses the encrypted source copy, adds that account
  to the key policy and the restore list, and copies into the new account.

Example, test account:
    ./bin/copy_ia_sql_snapshot.py \\
        --source-profile jcc-official-psypact-beta \\
        --target-profile jcc-ia-psypact-test \\
        --target-account-id 965304992797

Then set the printed snapshot id as ia_source_snapshot_id on that environment's
SSM context ({env}-psypact-context).
"""

import argparse
import json
import logging
import time

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

DEFAULT_SOURCE_SNAPSHOT_ARN = 'arn:aws:rds:us-east-1:440342401730:snapshot:asppb-ia-inspiringapps-v1'
DEFAULT_SNAPSHOT_ID = 'ia-inspiringapps-v1'
SOURCE_KEY_ALIAS = 'alias/ia-sql-snapshot-share'
TARGET_KEY_ALIAS = 'alias/ia-sql-snapshot'
DESTINATION_SID = 'AllowDestinationSnapshotCopy'
COPY_ACTIONS = ['kms:CreateGrant', 'kms:Decrypt', 'kms:DescribeKey']


def source_key_policy(source_account_id: str, target_account_ids: list[str]) -> dict:
    """Key policy for the encrypted snapshot copy that destinations are allowed to copy."""
    principals = [f'arn:aws:iam::{account_id}:root' for account_id in target_account_ids]
    principal: str | list[str] = principals[0] if len(principals) == 1 else principals
    return {
        'Version': '2012-10-17',
        'Statement': [
            {
                'Sid': 'EnableSourceAccountIam',
                'Effect': 'Allow',
                'Principal': {'AWS': f'arn:aws:iam::{source_account_id}:root'},
                'Action': 'kms:*',
                'Resource': '*',
            },
            {
                'Sid': DESTINATION_SID,
                'Effect': 'Allow',
                'Principal': {'AWS': principal},
                'Action': COPY_ACTIONS,
                'Resource': '*',
            },
        ],
    }


def add_destination_account(policy: dict, target_account_id: str) -> dict:
    """Return a policy that grants snapshot-copy permissions to one more destination account."""
    target_arn = f'arn:aws:iam::{target_account_id}:root'
    statements = policy.get('Statement', [])
    destination = next((statement for statement in statements if statement.get('Sid') == DESTINATION_SID), None)
    if destination is None:
        source_principal = next(
            statement['Principal']['AWS']
            for statement in statements
            if statement.get('Sid') == 'EnableSourceAccountIam'
        )
        # arn:aws:iam::<account>:root
        source_account_id = source_principal.split(':')[4]
        return source_key_policy(source_account_id, [target_account_id])

    current = destination['Principal']['AWS']
    current_arns = [current] if isinstance(current, str) else list(current)
    if target_arn not in current_arns:
        current_arns.append(target_arn)
    destination['Principal']['AWS'] = current_arns[0] if len(current_arns) == 1 else current_arns
    destination['Action'] = COPY_ACTIONS
    return policy


def client(profile: str, region: str, service_name: str):
    return boto3.Session(profile_name=profile, region_name=region).client(service_name)


def account_id(profile: str, region: str) -> str:
    return client(profile, region, 'sts').get_caller_identity()['Account']


def _alias_key_id(profile: str, region: str, alias_name: str) -> str | None:
    kms = client(profile, region, 'kms')
    paginator = kms.get_paginator('list_aliases')
    for page in paginator.paginate():
        for alias in page.get('Aliases', []):
            if alias.get('AliasName') == alias_name and alias.get('TargetKeyId'):
                return alias['TargetKeyId']
    return None


def ensure_cmk(profile: str, region: str, alias_name: str, description: str, policy: dict | None) -> str:
    """Create or reuse a customer-managed key with rotation enabled. Returns the key id."""
    kms = client(profile, region, 'kms')
    key_id = _alias_key_id(profile, region, alias_name)
    if key_id is None:
        create_args = {'Description': description}
        if policy is not None:
            create_args['Policy'] = json.dumps(policy)
        key_id = kms.create_key(**create_args)['KeyMetadata']['KeyId']
        kms.create_alias(AliasName=alias_name, TargetKeyId=key_id)
        logger.info('Created %s (%s)', alias_name, key_id)
    else:
        logger.info('Reusing %s (%s)', alias_name, key_id)
        if policy is not None:
            kms.put_key_policy(KeyId=key_id, PolicyName='default', Policy=json.dumps(policy))
    kms.enable_key_rotation(KeyId=key_id)
    return key_id


def ensure_source_key(profile: str, region: str, source_account_id: str, target_account_id: str) -> str:
    """Ensure the share key exists and grants this destination account copy permissions."""
    description = 'Encrypt the PSY|PRO SQL snapshot shared with destination accounts'
    key_id = _alias_key_id(profile, region, SOURCE_KEY_ALIAS)
    if key_id is None:
        return ensure_cmk(
            profile,
            region,
            SOURCE_KEY_ALIAS,
            description,
            source_key_policy(source_account_id, [target_account_id]),
        )
    current = client(profile, region, 'kms').get_key_policy(KeyId=key_id, PolicyName='default')
    policy = add_destination_account(json.loads(current['Policy']), target_account_id)
    return ensure_cmk(profile, region, SOURCE_KEY_ALIAS, description, policy)


def snapshot_description(profile: str, region: str, snapshot_id: str) -> dict | None:
    try:
        described = client(profile, region, 'rds').describe_db_snapshots(DBSnapshotIdentifier=snapshot_id)
    except ClientError as exc:
        if exc.response.get('Error', {}).get('Code') == 'DBSnapshotNotFound':
            return None
        raise
    snapshots = described.get('DBSnapshots', [])
    return snapshots[0] if snapshots else None


def wait_for_snapshot(profile: str, region: str, snapshot_id: str) -> dict:
    """Poll until a snapshot is available. Fails if the copy ends in an error status."""
    while True:
        snapshot = snapshot_description(profile, region, snapshot_id)
        if snapshot is None:
            raise RuntimeError(f'Snapshot {snapshot_id} disappeared while waiting')
        status = snapshot['Status']
        logger.info('%s status: %s', snapshot_id, status)
        if status == 'available':
            if not snapshot.get('Encrypted'):
                raise RuntimeError(f'Snapshot {snapshot_id} is available but not encrypted')
            return snapshot
        if status in {'failed', 'deleted', 'incompatible-parameters', 'incompatible-restore'}:
            raise RuntimeError(f'Snapshot {snapshot_id} entered status {status}')
        time.sleep(30)


def ensure_encrypted_copy(
    profile: str,
    region: str,
    snapshot_id: str,
    source_snapshot_id: str,
    kms_key_id: str,
) -> dict:
    """Copy a snapshot if this account does not already have an encrypted one with this id."""
    existing = snapshot_description(profile, region, snapshot_id)
    if existing is None:
        logger.info('Copying %s to %s', source_snapshot_id, snapshot_id)
        # AWS rejects CopyTags when the source snapshot is shared from another account.
        client(profile, region, 'rds').copy_db_snapshot(
            SourceDBSnapshotIdentifier=source_snapshot_id,
            TargetDBSnapshotIdentifier=snapshot_id,
            KmsKeyId=kms_key_id,
        )
    return wait_for_snapshot(profile, region, snapshot_id)


def share_snapshot(profile: str, region: str, snapshot_id: str, target_account_id: str) -> None:
    client(profile, region, 'rds').modify_db_snapshot_attribute(
        DBSnapshotIdentifier=snapshot_id,
        AttributeName='restore',
        ValuesToAdd=[target_account_id],
    )
    logger.info('Shared %s with account %s', snapshot_id, target_account_id)


def copy_snapshot(
    source_profile: str,
    target_profile: str,
    region: str,
    source_snapshot_arn: str,
    target_account_id: str,
    snapshot_id: str,
) -> str:
    """Encrypt, share, and copy the snapshot. Returns the destination snapshot id."""
    source_account_id = account_id(source_profile, region)
    caller_target_account_id = account_id(target_profile, region)
    if caller_target_account_id != target_account_id:
        raise RuntimeError(f'{target_profile} is account {caller_target_account_id}, not {target_account_id}')

    source_key_id = ensure_source_key(source_profile, region, source_account_id, target_account_id)
    source_copy = ensure_encrypted_copy(
        source_profile,
        region,
        snapshot_id,
        source_snapshot_arn,
        source_key_id,
    )
    share_snapshot(source_profile, region, snapshot_id, target_account_id)

    target_key_id = ensure_cmk(
        target_profile,
        region,
        TARGET_KEY_ALIAS,
        'Encrypt the PSY|PRO SQL snapshot owned by this account',
        None,
    )
    ensure_encrypted_copy(
        target_profile,
        region,
        snapshot_id,
        source_copy['DBSnapshotArn'],
        target_key_id,
    )
    return snapshot_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Copy the PSY|PRO SQL snapshot into a destination account, encrypted.')
    parser.add_argument('--source-profile', required=True)
    parser.add_argument('--target-profile', required=True)
    parser.add_argument('--target-account-id', required=True)
    parser.add_argument('--source-snapshot-arn', default=DEFAULT_SOURCE_SNAPSHOT_ARN)
    parser.add_argument('--snapshot-id', default=DEFAULT_SNAPSHOT_ID)
    parser.add_argument('--region', default='us-east-1')
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    args = parse_args()
    snapshot_id = copy_snapshot(
        source_profile=args.source_profile,
        target_profile=args.target_profile,
        region=args.region,
        source_snapshot_arn=args.source_snapshot_arn,
        target_account_id=args.target_account_id,
        snapshot_id=args.snapshot_id,
    )
    logger.info('Destination snapshot id: %s', snapshot_id)
    logger.info(
        'Set ia_source_snapshot_id to %s on this environment SSM context before the pipeline deploy.',
        snapshot_id,
    )


if __name__ == '__main__':
    main()
