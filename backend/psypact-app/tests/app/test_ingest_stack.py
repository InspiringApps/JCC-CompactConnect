from unittest import TestCase

from tests.app.base import TstAppABC


class TestIngestStack(TstAppABC, TestCase):
    @classmethod
    def get_context(cls):
        import json

        with open('cdk.json') as f:
            context = json.load(f)['context']
        with open('cdk.context.sandbox-example.json') as f:
            context.update(json.load(f))
        context['aws:cdk:bundling-stacks'] = []
        return context

    def test_ingest_stack_is_not_wired(self):
        self.assertFalse(hasattr(self.app.sandbox_backend_stage, 'ingest_stack'))
