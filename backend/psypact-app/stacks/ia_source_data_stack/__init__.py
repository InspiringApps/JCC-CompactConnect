import json
import os

from aws_cdk import Duration, RemovalPolicy
from aws_cdk.aws_dynamodb import (
    Attribute,
    AttributeType,
    BillingMode,
    PointInTimeRecoverySpecification,
    Table,
    TableEncryption,
)
from aws_cdk.aws_ec2 import (
    InstanceClass,
    InstanceSize,
    InstanceType,
    Peer,
    Port,
    SecurityGroup,
    SubnetSelection,
    SubnetType,
)
from aws_cdk.aws_kms import Key
from aws_cdk.aws_rds import (
    DatabaseInstanceEngine,
    DatabaseInstanceFromSnapshot,
    LicenseModel,
    SqlServerEngineVersion,
    StorageType,
)
from cdk_nag import NagSuppressions
from common_constructs.stack import AppStack
from constructs import Construct

from stacks.vpc_stack import VpcStack

# Shared snapshot arn:aws:rds:us-east-1:440342401730:snapshot:asppb-ia-inspiringapps-v1
# and the instance restored from it in account 220133864196.
SOURCE_ENGINE = 'sqlserver-web'
SOURCE_ENGINE_VERSION = '16.00.4095.4.v1'
SOURCE_ENGINE_MAJOR_VERSION = '16.00'
SOURCE_INSTANCE_CLASS = 'db.m8i.large'
SOURCE_ALLOCATED_STORAGE = 20
SOURCE_STORAGE_TYPE = 'gp2'
SOURCE_IOPS = None
SOURCE_LICENSE_MODEL = 'license-included'
SOURCE_MULTI_AZ = False
TABLE_NAME_PREFIX = 'IA.'

_SCHEMA_INDEX_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'docs', 'dynamodb_table_structures_2', '_index.json')
)

_NUMBER_KEYS = {'userId', 'entryId', 'activityId', 'attestationId', 'disciplinaryEntryId'}
_STRING_KEYS = {'attesterEmail'}

_ENGINE_FACTORIES = {
    'sqlserver-ee': DatabaseInstanceEngine.sql_server_ee,
    'sqlserver-se': DatabaseInstanceEngine.sql_server_se,
    'sqlserver-ex': DatabaseInstanceEngine.sql_server_ex,
    'sqlserver-web': DatabaseInstanceEngine.sql_server_web,
}

_LICENSE_MODELS = {
    'license-included': LicenseModel.LICENSE_INCLUDED,
    'bring-your-own-license': LicenseModel.BRING_YOUR_OWN_LICENSE,
}

_STORAGE_TYPES = {
    'gp2': StorageType.GP2,
    'gp3': StorageType.GP3,
    'io1': StorageType.IO1,
    'io2': StorageType.IO2,
}

_INSTANCE_CLASSES = {
    't3': InstanceClass.BURSTABLE3,
    't4g': InstanceClass.BURSTABLE4_GRAVITON,
    'm5': InstanceClass.STANDARD5,
    'm6i': InstanceClass.STANDARD6_INTEL,
    'm6g': InstanceClass.STANDARD6_GRAVITON,
    'm7g': InstanceClass.STANDARD7_GRAVITON,
    'm8i': InstanceClass.M8I,
    'r5': InstanceClass.MEMORY5,
    'r6i': InstanceClass.MEMORY6_INTEL,
    'r6g': InstanceClass.MEMORY6_GRAVITON,
    'r7g': InstanceClass.MEMORY7_GRAVITON,
}

_INSTANCE_SIZES = {
    'micro': InstanceSize.MICRO,
    'small': InstanceSize.SMALL,
    'medium': InstanceSize.MEDIUM,
    'large': InstanceSize.LARGE,
    'xlarge': InstanceSize.XLARGE,
    '2xlarge': InstanceSize.XLARGE2,
    '4xlarge': InstanceSize.XLARGE4,
    '8xlarge': InstanceSize.XLARGE8,
    '12xlarge': InstanceSize.XLARGE12,
    '16xlarge': InstanceSize.XLARGE16,
    '24xlarge': InstanceSize.XLARGE24,
}


def _attribute_type(name: str) -> AttributeType:
    if name in _NUMBER_KEYS:
        return AttributeType.NUMBER
    if name in _STRING_KEYS:
        return AttributeType.STRING
    raise ValueError(f'No DynamoDB type mapping for key {name}')


def _instance_type(instance_class: str) -> InstanceType:
    """Convert an RDS class such as db.t3.xlarge into a CDK instance type."""
    family, size = instance_class.removeprefix('db.').split('.', maxsplit=1)
    try:
        return InstanceType.of(_INSTANCE_CLASSES[family], _INSTANCE_SIZES[size])
    except KeyError as exc:
        raise ValueError(f'Unsupported RDS instance class {instance_class}') from exc


class IaSourceDataStack(AppStack):
    """
    PSY|PRO source data for an environment that has opted in.

    Created only when environment context includes ia_source_snapshot_id. That id is the
    encrypted snapshot produced by bin/copy_ia_sql_snapshot.py in this account. The DynamoDB
    tables match the Inspiring Apps export key schema. SQL Server is restored from the snapshot.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        environment_name: str,
        environment_context: dict,
        vpc_stack: VpcStack,
        snapshot_identifier: str,
        **kwargs,
    ):
        super().__init__(
            scope,
            construct_id,
            environment_context=environment_context,
            environment_name=environment_name,
            **kwargs,
        )

        removal_policy = RemovalPolicy.RETAIN if environment_name == 'prod' else RemovalPolicy.DESTROY
        self.encryption_key = Key(
            self,
            'IaSourceDataKey',
            enable_key_rotation=True,
            alias='ia-source-data',
            removal_policy=removal_policy,
        )
        self.tables = self._create_tables(removal_policy)
        self.database = self._create_database(
            vpc_stack=vpc_stack,
            snapshot_identifier=snapshot_identifier,
            removal_policy=removal_policy,
            environment_name=environment_name,
        )

    def _create_tables(self, removal_policy: RemovalPolicy) -> dict[str, Table]:
        with open(_SCHEMA_INDEX_PATH, encoding='utf-8') as schema_index_file:
            schema_index = json.load(schema_index_file)

        tables = {}
        for table_schema in schema_index['tables']:
            table_name = f'{TABLE_NAME_PREFIX}{table_schema["tableName"]}'
            partition_key_name = table_schema['partitionKey']
            sort_key_name = table_schema['sortKey']
            table = Table(
                self,
                table_name.replace('.', '_'),
                table_name=table_name,
                encryption=TableEncryption.CUSTOMER_MANAGED,
                encryption_key=self.encryption_key,
                billing_mode=BillingMode.PAY_PER_REQUEST,
                removal_policy=removal_policy,
                deletion_protection=removal_policy == RemovalPolicy.RETAIN,
                point_in_time_recovery_specification=PointInTimeRecoverySpecification(
                    point_in_time_recovery_enabled=False
                ),
                partition_key=Attribute(name=partition_key_name, type=_attribute_type(partition_key_name)),
                sort_key=(
                    Attribute(name=sort_key_name, type=_attribute_type(sort_key_name)) if sort_key_name else None
                ),
            )
            NagSuppressions.add_resource_suppressions(
                table,
                suppressions=[
                    {
                        'id': 'HIPAA.Security-DynamoDBInBackupPlan',
                        'reason': 'This table is a static copy of the PSY|PRO export. The export and SQL snapshot '
                        'are the recovery source, so a backup plan is not attached.',
                    },
                    {
                        'id': 'HIPAA.Security-DynamoDBPITREnabled',
                        'reason': 'This table is loaded once from a static export. Point-in-time recovery is not '
                        'needed for a fixture copy.',
                    },
                    {
                        'id': 'AwsSolutions-DDB3',
                        'reason': 'This table is loaded once from a static export. Point-in-time recovery is not '
                        'needed for a fixture copy.',
                    },
                ],
            )
            tables[table_name] = table
        return tables

    def _create_database(
        self,
        *,
        vpc_stack: VpcStack,
        snapshot_identifier: str,
        removal_policy: RemovalPolicy,
        environment_name: str,
    ) -> DatabaseInstanceFromSnapshot:
        vpc = vpc_stack.vpc
        security_group = SecurityGroup(
            self,
            'IaSqlServerSecurityGroup',
            vpc=vpc,
            description='SQL Server access for the PSY|PRO source database',
            allow_all_outbound=False,
        )
        # Literal CIDR matches VpcStack. A cross-stack token cannot be evaluated by cdk-nag.
        security_group.add_ingress_rule(
            Peer.ipv4('10.0.0.0/16'),
            Port.tcp(1433),
            'SQL Server from the application VPC',
        )
        NagSuppressions.add_resource_suppressions(
            security_group,
            suppressions=[
                {
                    'id': 'HIPAA.Security-EC2RestrictedCommonPorts',
                    'reason': 'Port 1433 is the SQL Server port. Ingress is limited to the application VPC CIDR.',
                },
            ],
            apply_to_children=True,
        )

        engine_factory = _ENGINE_FACTORIES[SOURCE_ENGINE]
        database_kwargs = {}
        if SOURCE_IOPS is not None:
            database_kwargs['iops'] = SOURCE_IOPS
        database = DatabaseInstanceFromSnapshot(
            self,
            'IaSqlServer',
            snapshot_identifier=snapshot_identifier,
            instance_identifier=f'ia-source-sqlserver-{environment_name}',
            engine=engine_factory(
                version=SqlServerEngineVersion.of(SOURCE_ENGINE_VERSION, SOURCE_ENGINE_MAJOR_VERSION),
            ),
            instance_type=_instance_type(SOURCE_INSTANCE_CLASS),
            vpc=vpc,
            vpc_subnets=SubnetSelection(subnet_type=SubnetType.PRIVATE_ISOLATED),
            security_groups=[security_group],
            publicly_accessible=False,
            multi_az=SOURCE_MULTI_AZ,
            allocated_storage=SOURCE_ALLOCATED_STORAGE,
            storage_type=_STORAGE_TYPES[SOURCE_STORAGE_TYPE],
            license_model=_LICENSE_MODELS[SOURCE_LICENSE_MODEL],
            deletion_protection=removal_policy == RemovalPolicy.RETAIN,
            removal_policy=removal_policy,
            backup_retention=Duration.days(7),
            preferred_backup_window='05:00-06:00',
            preferred_maintenance_window='sun:06:30-sun:07:30',
            cloudwatch_logs_exports=['agent', 'error'],
            auto_minor_version_upgrade=True,
            copy_tags_to_snapshot=True,
            **database_kwargs,
        )
        # Encryption is taken from the copied snapshot. Set it explicitly so the template
        # shows the instance is encrypted at rest.
        database.node.default_child.storage_encrypted = True
        database_suppressions = [
            {
                'id': 'AwsSolutions-RDS6',
                'reason': 'Enhanced monitoring is omitted for this restored fixture database.',
            },
            {
                'id': 'HIPAA.Security-RDSEnhancedMonitoringEnabled',
                'reason': 'Enhanced monitoring is omitted for this restored fixture database.',
            },
            {
                'id': 'AwsSolutions-RDS11',
                'reason': 'The instance stays encrypted with the customer-managed key already on the copied '
                'snapshot. A different key in this stack would not match that snapshot.',
            },
            {
                'id': 'HIPAA.Security-RDSInBackupPlan',
                'reason': 'Automated backups are enabled. A separate AWS Backup plan is not attached because this '
                'instance is itself a restore of a shared snapshot.',
            },
        ]
        if not SOURCE_MULTI_AZ:
            database_suppressions.extend(
                [
                    {
                        'id': 'AwsSolutions-RDS3',
                        'reason': 'The source snapshot is a single-AZ SQL Server instance, and the restore matches it.',
                    },
                    {
                        'id': 'HIPAA.Security-RDSMultiAZSupport',
                        'reason': 'The source snapshot is a single-AZ SQL Server instance, and the restore matches it.',
                    },
                ]
            )
        if removal_policy != RemovalPolicy.RETAIN:
            database_suppressions.extend(
                [
                    {
                        'id': 'AwsSolutions-RDS10',
                        'reason': 'Deletion protection is off outside production so this fixture stack can be removed.',
                    },
                    {
                        'id': 'HIPAA.Security-RDSInstanceDeletionProtectionEnabled',
                        'reason': 'Deletion protection is off outside production so this fixture stack can be removed.',
                    },
                ]
            )
        NagSuppressions.add_resource_suppressions(database, suppressions=database_suppressions, apply_to_children=True)
        return database
