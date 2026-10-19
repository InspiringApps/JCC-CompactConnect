import json
import os

import jsii
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
    InterfaceVpcEndpoint,
    InterfaceVpcEndpointAwsService,
    Peer,
    Port,
    SecurityGroup,
    SubnetSelection,
    SubnetType,
)
from aws_cdk.aws_iam import PolicyStatement
from aws_cdk.aws_kms import Key
from aws_cdk.aws_lambda import Runtime
from aws_cdk.aws_lambda_python_alpha import BundlingOptions, ICommandHooks
from aws_cdk.aws_rds import (
    DatabaseInstanceEngine,
    DatabaseInstanceFromSnapshot,
    LicenseModel,
    SnapshotCredentials,
    SqlServerEngineVersion,
    StorageType,
)
from cdk_nag import NagSuppressions
from common_constructs.python_function import PythonFunction
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
# RDS cannot change the master username of a restored snapshot. This must be that username.
SOURCE_MASTER_USERNAME = 'admin'
TABLE_NAME_PREFIX = 'Psypro.'
# Public Amazon RDS trust bundle. It is not a credential, so it is fetched into the
# lambda asset at build time and is not stored in git or Secrets Manager.
RDS_CA_BUNDLE_FILENAME = 'rds-global-bundle.pem'
RDS_CA_BUNDLE_URL = 'https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem'

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


@jsii.implements(ICommandHooks)
class RdsCaBundleHooks:
    """Fetch the public RDS CA into the packaged lambda asset."""

    def before_bundling(self, _input_dir: str, _output_dir: str) -> list[str]:
        return []

    def after_bundling(self, _input_dir: str, output_dir: str) -> list[str]:
        destination = f'{output_dir}/{RDS_CA_BUNDLE_FILENAME}'
        return [
            'python -c "import urllib.request; urllib.request.urlretrieve('
            f"'{RDS_CA_BUNDLE_URL}', '{destination}')\""
        ]


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
        self.query_function = self._create_query_function(vpc_stack)

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
            description='SQL Server access for the Inspiring Apps source database',
            allow_all_outbound=False,
        )
        self.database_security_group = security_group
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
            credentials=SnapshotCredentials.from_generated_secret(
                SOURCE_MASTER_USERNAME,
                encryption_key=self.encryption_key,
            ),
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
        # Do not set StorageEncrypted. CloudFormation rejects it when DBSnapshotIdentifier
        # is set. The copied snapshot is already encrypted, and the restore keeps that key.
        database_suppressions = [
            {
                'id': 'AwsSolutions-RDS2',
                'reason': 'The instance is restored from an encrypted snapshot, so storage encryption is inherited. '
                'CloudFormation rejects StorageEncrypted when DBSnapshotIdentifier is set.',
            },
            {
                'id': 'HIPAA.Security-RDSStorageEncrypted',
                'reason': 'The instance is restored from an encrypted snapshot, so storage encryption is inherited. '
                'CloudFormation rejects StorageEncrypted when DBSnapshotIdentifier is set.',
            },
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

    def _create_query_function(self, vpc_stack: VpcStack) -> PythonFunction:
        """Lambda in the database subnets that can query SQL Server and read Psypro tables."""
        vpc = vpc_stack.vpc
        secrets_endpoint = InterfaceVpcEndpoint(
            self,
            'SecretsManagerEndpoint',
            vpc=vpc,
            service=InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
            subnets=SubnetSelection(subnet_type=SubnetType.PRIVATE_ISOLATED),
            private_dns_enabled=True,
            open=True,
            lookup_supported_azs=False,
        )
        NagSuppressions.add_resource_suppressions(
            secrets_endpoint,
            suppressions=[
                {
                    'id': 'AwsSolutions-EC23',
                    'reason': 'The endpoint security group is managed by CDK and allows HTTPS from the VPC CIDR only.',
                },
                {
                    'id': 'HIPAA.Security-EC2RestrictedCommonPorts',
                    'reason': 'The endpoint security group allows HTTPS from the VPC so the query lambda can read '
                    'the database secret. It is not open to the internet.',
                },
                {
                    'id': 'HIPAA.Security-EC2RestrictedSSH',
                    'reason': 'SSH is not enabled on the Secrets Manager endpoint security group.',
                },
            ],
            apply_to_children=True,
        )

        query_security_group = SecurityGroup(
            self,
            'PsyproSourceQuerySecurityGroup',
            vpc=vpc,
            description='PSYPRO source query lambda',
            allow_all_outbound=False,
        )
        query_security_group.add_egress_rule(
            self.database_security_group,
            Port.tcp(1433),
            'SQL Server on the PSYPRO source database',
        )
        # Interface endpoints use private IPs in the VPC. The DynamoDB gateway endpoint uses the
        # AWS managed prefix list, which is public addresses, so HTTPS egress cannot be the VPC CIDR alone.
        query_security_group.add_egress_rule(
            Peer.any_ipv4(),
            Port.tcp(443),
            'HTTPS to DynamoDB and Secrets Manager endpoints',
        )
        NagSuppressions.add_resource_suppressions(
            query_security_group,
            suppressions=[
                {
                    'id': 'HIPAA.Security-EC2RestrictedCommonPorts',
                    'reason': 'Outbound HTTPS is required for the DynamoDB gateway endpoint and the Secrets Manager '
                    'interface endpoint. The lambda has no inbound rules.',
                },
            ],
            apply_to_children=True,
        )

        if self.database.secret is None:
            raise RuntimeError('PSYPRO source database secret was not created')
        NagSuppressions.add_resource_suppressions_by_path(
            self,
            f'{self.database.node.path}/Secret/Resource',
            [
                {
                    'id': 'AwsSolutions-SMG4',
                    'reason': 'This secret holds the generated master password for a restored fixture database. '
                    'Automatic rotation would change that password while a migration is using it.',
                },
                {
                    'id': 'HIPAA.Security-SecretsManagerRotationEnabled',
                    'reason': 'This secret holds the generated master password for a restored fixture database. '
                    'Automatic rotation would change that password while a migration is using it.',
                },
            ],
        )
        query_function = PythonFunction(
            self,
            'PsyproSourceQuery',
            description='Query the PSYPRO source SQL Server database',
            lambda_dir='psypro-source-query',
            index='handler.py',
            handler='query_psypro_source',
            runtime=Runtime.PYTHON_3_14,
            timeout=Duration.minutes(5),
            memory_size=512,
            reserved_concurrent_executions=1,
            vpc=vpc,
            vpc_subnets=SubnetSelection(subnet_type=SubnetType.PRIVATE_ISOLATED),
            security_groups=[query_security_group],
            bundling=BundlingOptions(command_hooks=RdsCaBundleHooks()),
            environment={
                'PSYPRO_SQL_SECRET_ARN': self.database.secret.secret_arn,
                'PSYPRO_SQL_HOST': self.database.db_instance_endpoint_address,
                'PSYPRO_SQL_PORT': self.database.db_instance_endpoint_port,
                'PSYPRO_TABLE_PREFIX': TABLE_NAME_PREFIX,
                **self.common_env_vars,
            },
        )
        query_function.node.add_dependency(secrets_endpoint)
        self.database.secret.grant_read(query_function)
        self.encryption_key.grant_decrypt(query_function)
        query_function.add_to_role_policy(
            PolicyStatement(
                actions=[
                    'dynamodb:BatchGetItem',
                    'dynamodb:DescribeTable',
                    'dynamodb:GetItem',
                    'dynamodb:Query',
                    'dynamodb:Scan',
                ],
                resources=[table.table_arn for table in self.tables.values()],
            )
        )
        NagSuppressions.add_resource_suppressions_by_path(
            self,
            f'{query_function.role.node.path}/DefaultPolicy/Resource',
            [
                {
                    'id': 'AwsSolutions-IAM5',
                    'reason': 'Reading the generated database secret includes its version suffix. DynamoDB access is '
                    'limited to the Psypro source tables.',
                },
            ],
        )
        return query_function
