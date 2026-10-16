import json
from unittest import TestCase

from aws_cdk.assertions import Template

from tests.app.base import TstAppABC
from tests.app.test_sandbox import TstSandbox


class TestIaSourceDataStack(TstAppABC, TestCase):
    """BackendStage with ia_source_snapshot_id creates the PSY|PRO source tables and database."""

    @classmethod
    def get_context(cls):
        context = TstSandbox.get_context()
        environment_name = context['environment_name']
        context['ssm_context']['environments'][environment_name]['ia_source_snapshot_id'] = 'ia-inspiringapps-v1'
        return context

    def test_tables_and_database(self):
        stack = self.app.sandbox_backend_stage.ia_source_data_stack
        self.assertIsNotNone(stack)
        template = Template.from_stack(stack)

        template.resource_count_is('AWS::DynamoDB::Table', 37)
        template.resource_count_is('AWS::RDS::DBInstance', 1)
        template.has_resource_properties(
            'AWS::RDS::DBInstance',
            {
                'PubliclyAccessible': False,
                'StorageEncrypted': True,
                'DBSnapshotIdentifier': 'ia-inspiringapps-v1',
            },
        )

        with open('docs/dynamodb_table_structures_2/_index.json', encoding='utf-8') as schema_index_file:
            schema_index = json.load(schema_index_file)

        number_keys = {'userId', 'entryId', 'activityId', 'attestationId', 'disciplinaryEntryId'}
        for table_schema in schema_index['tables']:
            attribute_definitions = [
                {
                    'AttributeName': table_schema['partitionKey'],
                    'AttributeType': 'N' if table_schema['partitionKey'] in number_keys else 'S',
                }
            ]
            key_schema = [{'AttributeName': table_schema['partitionKey'], 'KeyType': 'HASH'}]
            if table_schema['sortKey']:
                attribute_definitions.append(
                    {
                        'AttributeName': table_schema['sortKey'],
                        'AttributeType': 'N' if table_schema['sortKey'] in number_keys else 'S',
                    }
                )
                key_schema.append({'AttributeName': table_schema['sortKey'], 'KeyType': 'RANGE'})

            template.has_resource_properties(
                'AWS::DynamoDB::Table',
                {
                    'TableName': f'IA.{table_schema["tableName"]}',
                    'BillingMode': 'PAY_PER_REQUEST',
                    'KeySchema': key_schema,
                    'AttributeDefinitions': attribute_definitions,
                },
            )

        self._check_no_stack_annotations(stack)
        self._check_backend_stage_resource_counts(self.app.sandbox_backend_stage)


class TestIaSourceDataStackOmitted(TstAppABC, TestCase):
    """Sandbox context without a snapshot id does not create the source data stack."""

    @classmethod
    def get_context(cls):
        return TstSandbox.get_context()

    def test_stack_omitted_without_snapshot_id(self):
        self.assertIsNone(self.app.sandbox_backend_stage.ia_source_data_stack)
