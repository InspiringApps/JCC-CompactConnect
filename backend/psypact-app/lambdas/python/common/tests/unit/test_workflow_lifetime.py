import os
from datetime import timedelta
from unittest import TestCase

from cc_common.applicants.workflow_lifetime import workflow_lifetime


class TestWorkflowLifetime(TestCase):
    def setUp(self):  # noqa: N801 invalid-name
        super().setUp()
        self._environment_name = os.environ.get('ENVIRONMENT_NAME')

    def tearDown(self):  # noqa: N801 invalid-name
        os.environ.pop('APPLICATION_WORKFLOW_LIFETIME_SECONDS', None)
        if self._environment_name is None:
            os.environ.pop('ENVIRONMENT_NAME', None)
        else:
            os.environ['ENVIRONMENT_NAME'] = self._environment_name
        super().tearDown()

    def test_official_environments_keep_the_one_year_lifetime(self):
        os.environ['ENVIRONMENT_NAME'] = 'prod'
        os.environ['APPLICATION_WORKFLOW_LIFETIME_SECONDS'] = '30'

        self.assertEqual(timedelta(days=365), workflow_lifetime())

    def test_a_sandbox_override_is_honored(self):
        os.environ['ENVIRONMENT_NAME'] = 'sandbox'
        os.environ['APPLICATION_WORKFLOW_LIFETIME_SECONDS'] = '90'

        self.assertEqual(timedelta(seconds=90), workflow_lifetime())
