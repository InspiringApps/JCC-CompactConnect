from tests.app.test_api import TestApi


class TestAttestationsApi(TestApi):
    def test_attestations_api_is_wired(self):
        v1_api = self.app.sandbox_backend_stage.api_stack.api.v1_api
        self.assertTrue(hasattr(v1_api, 'attestations'))
        self.assertTrue(hasattr(self.app.sandbox_backend_stage.api_lambda_stack, 'attestations_lambdas'))
