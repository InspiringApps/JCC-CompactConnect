from tests.app.test_api import TestApi


class TestStateApi(TestApi):
    def test_state_api_stack_is_not_wired(self):
        self.assertFalse(hasattr(self.app.sandbox_backend_stage, 'state_api_stack'))
