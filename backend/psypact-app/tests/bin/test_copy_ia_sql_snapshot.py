import importlib.util
import unittest
from pathlib import Path


def _load_script():
    script_path = Path(__file__).resolve().parents[2] / 'bin' / 'copy_ia_sql_snapshot.py'
    spec = importlib.util.spec_from_file_location('copy_ia_sql_snapshot', script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


copy_ia_sql_snapshot = _load_script()


class TestSnapshotKeyPolicy(unittest.TestCase):
    def test_source_policy_grants_only_copy_actions_to_the_destination(self):
        policy = copy_ia_sql_snapshot.source_key_policy('220133864196', ['965304992797'])

        destination = next(
            statement for statement in policy['Statement'] if statement['Sid'] == 'AllowDestinationSnapshotCopy'
        )
        self.assertEqual(destination['Principal']['AWS'], 'arn:aws:iam::965304992797:root')
        self.assertEqual(destination['Action'], ['kms:CreateGrant', 'kms:Decrypt', 'kms:DescribeKey'])

        source = next(statement for statement in policy['Statement'] if statement['Sid'] == 'EnableSourceAccountIam')
        self.assertEqual(source['Principal']['AWS'], 'arn:aws:iam::220133864196:root')

    def test_adding_another_destination_keeps_the_existing_account(self):
        policy = copy_ia_sql_snapshot.source_key_policy('220133864196', ['965304992797'])
        updated = copy_ia_sql_snapshot.add_destination_account(policy, '014566101402')

        destination = next(
            statement for statement in updated['Statement'] if statement['Sid'] == 'AllowDestinationSnapshotCopy'
        )
        self.assertEqual(
            destination['Principal']['AWS'],
            ['arn:aws:iam::965304992797:root', 'arn:aws:iam::014566101402:root'],
        )
        self.assertEqual(destination['Action'], ['kms:CreateGrant', 'kms:Decrypt', 'kms:DescribeKey'])

    def test_adding_the_same_destination_does_not_duplicate_it(self):
        policy = copy_ia_sql_snapshot.source_key_policy('220133864196', ['965304992797'])
        updated = copy_ia_sql_snapshot.add_destination_account(policy, '965304992797')

        destination = next(
            statement for statement in updated['Statement'] if statement['Sid'] == 'AllowDestinationSnapshotCopy'
        )
        self.assertEqual(destination['Principal']['AWS'], 'arn:aws:iam::965304992797:root')
