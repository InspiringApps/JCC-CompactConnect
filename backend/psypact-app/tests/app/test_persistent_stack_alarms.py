import json
from unittest import TestCase

from aws_cdk.assertions import Template

from stacks.persistent_stack import alarm_email_addresses
from tests.app.base import TstAppABC


class TestPersistentStackAlarms(TstAppABC, TestCase):
    @classmethod
    def get_context(cls):
        with open('cdk.json') as context_file:
            context = json.load(context_file)['context']
        context['aws:cdk:bundling-stacks'] = []
        return context

    def test_support_email_is_subscribed_without_changing_existing_recipients(self):
        stages = (
            self.app.test_backend_pipeline_stack.test_stage,
            self.app.prod_backend_pipeline_stack.prod_stage,
        )
        for stage in stages:
            with self.subTest(stage=stage.environment_name):
                notifications = stage.persistent_stack.environment_context.get('notifications', {})
                endpoints = _email_endpoints(Template.from_stack(stage.persistent_stack))
                self.assertEqual(alarm_email_addresses(notifications), endpoints)
                self.assertEqual(len(endpoints), len(set(endpoints)))
                support = notifications.get('ses_operations_support_email')
                if isinstance(support, str) and support:
                    self.assertEqual(1, endpoints.count(support))
                for address in _addresses(notifications.get('email')):
                    self.assertIn(address, endpoints)


def _email_endpoints(template: Template) -> list[str]:
    """Return email endpoints on the alarm topic, not the SES feedback topic."""
    endpoints = []
    for logical_id, resource in template.find_resources('AWS::SNS::Subscription').items():
        properties = resource['Properties']
        if properties.get('Protocol') != 'email' or 'AlarmTopic' not in logical_id:
            continue
        endpoints.append(properties['Endpoint'])
    return endpoints


def _addresses(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    return [address for address in value if address]
