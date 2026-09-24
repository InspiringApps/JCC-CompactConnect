from tests.app.test_api import TestApi


class TestPurchasesApi(TestApi):
    def test_privilege_purchase_routes_are_not_wired(self):
        v1_api = self.app.sandbox_backend_stage.api_stack.api.v1_api
        self.assertFalse(hasattr(v1_api, 'purchases'))
        self.assertFalse(hasattr(self.app.sandbox_backend_stage.api_lambda_stack, 'purchases_lambdas'))
