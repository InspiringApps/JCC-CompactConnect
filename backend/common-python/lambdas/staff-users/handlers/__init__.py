# Copied from backend/cosmetology-app/lambdas/python/staff-users/handlers/__init__.py

from aws_lambda_powertools import Logger
from common_lambdas.data_model.schema.user.api import UserAPISchema

logger = Logger()
user_api_schema = UserAPISchema()
