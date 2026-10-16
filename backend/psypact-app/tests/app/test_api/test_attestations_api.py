from tests.app.test_api import TestApi


class TestAttestationsApi(TestApi):
    def test_attestations_api_is_not_wired(self):
        v1_api = self.app.sandbox_backend_stage.api_stack.api.v1_api
        self.assertFalse(hasattr(v1_api, 'attestations'))
