import json
from unittest import TestCase

from aws_cdk.assertions import Template
from common_constructs.backup_plan import CCBackupPlan

from tests.app.base import TstAppABC
from tests.app.test_sandbox import TstSandbox


def _table_properties(stack) -> dict:
    template = Template.from_stack(stack)
    logical_id = stack.get_logical_id(stack.application_table.node.default_child)
    return template.find_resources('AWS::DynamoDB::Table')[logical_id]['Properties']


class TestApplicationTable(TstSandbox):
    def test_keys_indexes_encryption_and_recovery(self):
        stack = self.app.sandbox_backend_stage.persistent_stack
        table = stack.application_table
        self.assertEqual('statusGSI', table.status_gsi_name)
        self.assertEqual('actorGSI', table.actor_gsi_name)
        self.assertEqual('applicantGSI', table.applicant_gsi_name)
        self.assertIsNone(table.backup_plan)

        properties = _table_properties(stack)
        self.assertEqual(
            [
                {'AttributeName': 'pk', 'KeyType': 'HASH'},
                {'AttributeName': 'sk', 'KeyType': 'RANGE'},
            ],
            properties['KeySchema'],
        )
        self.assertEqual('PAY_PER_REQUEST', properties['BillingMode'])
        self.assertTrue(properties['PointInTimeRecoverySpecification']['PointInTimeRecoveryEnabled'])
        self.assertEqual('KMS', properties['SSESpecification']['SSEType'])
        self.assertTrue(properties['SSESpecification']['SSEEnabled'])
        self.assertIn('KMSMasterKeyId', properties['SSESpecification'])
        self.assertNotIn('StreamSpecification', properties)
        self.assertFalse(properties.get('DeletionProtectionEnabled', False))

        attribute_names = {attribute['AttributeName'] for attribute in properties['AttributeDefinitions']}
        self.assertTrue(
            {
                'pk',
                'sk',
                'statusGSIPK',
                'statusGSISK',
                'actorGSIPK',
                'actorGSISK',
                'applicantGSIPK',
                'applicantGSISK',
            }.issubset(attribute_names)
        )

        indexes = {index['IndexName']: index for index in properties['GlobalSecondaryIndexes']}
        self.assertEqual({'statusGSI', 'actorGSI', 'applicantGSI'}, set(indexes))
        for index_name, partition_key, sort_key in (
            ('statusGSI', 'statusGSIPK', 'statusGSISK'),
            ('actorGSI', 'actorGSIPK', 'actorGSISK'),
            ('applicantGSI', 'applicantGSIPK', 'applicantGSISK'),
        ):
            self.assertEqual(
                [
                    {'AttributeName': partition_key, 'KeyType': 'HASH'},
                    {'AttributeName': sort_key, 'KeyType': 'RANGE'},
                ],
                indexes[index_name]['KeySchema'],
            )
            self.assertEqual('ALL', indexes[index_name]['Projection']['ProjectionType'])

    def test_disaster_recovery_restore_workflow(self):
        stage = self.app.sandbox_backend_stage
        table = stage.persistent_stack.application_table
        workflow = stage.disaster_recovery_stack.dr_workflows[table.table_name]

        self.assertEqual('DR-RestoreTableStepFunction-ApplicationTable', workflow.node.id)
        template = Template.from_stack(stage.disaster_recovery_stack)
        logical_id = stage.disaster_recovery_stack.get_logical_id(workflow.state_machine.node.default_child)
        self.assertIn(logical_id, template.find_resources('AWS::StepFunctions::StateMachine'))


class TestApplicationTableBackups(TstAppABC, TestCase):
    @classmethod
    def get_context(cls):
        with open('cdk.json') as f:
            context = json.load(f)['context']
        with open('cdk.context.test-example.json') as f:
            context.update(json.load(f))

        # Suppresses lambda bundling for tests
        context['aws:cdk:bundling-stacks'] = []
        return context

    def test_backup_plan_when_backups_enabled(self):
        stack = self.app.test_backend_pipeline_stack.test_stage.persistent_stack
        self.assertIsInstance(stack.application_table.backup_plan, CCBackupPlan)
        self.assertFalse(_table_properties(stack).get('DeletionProtectionEnabled', False))

    def test_deletion_protection_when_retained(self):
        stack = self.app.prod_backend_pipeline_stack.prod_stage.persistent_stack
        self.assertTrue(_table_properties(stack)['DeletionProtectionEnabled'])
