"""PSYPACT wrapper around the shared API Gateway decorator.

``api_handler`` returns HTTP 200 for a normal result and re-raises
``CCConflictException`` after logging it. This wrapper turns that exception
into HTTP 409. A successful body with ``pending`` set is an accepted
transition that has not settled yet, so the status becomes 202.
"""

import json
from functools import wraps

from common_lambdas import config as config_module
from common_lambdas.exceptions import CCConflictException
from common_lambdas.utils import api_handler


def api_handler_psypact(fn):
    """Decorate a route with the shared handler, then map PSYPACT status codes."""
    handled = api_handler(fn)

    @wraps(fn)
    def mapped(event, context):
        try:
            response = handled(event, context)
        except CCConflictException as error:
            return {
                'headers': _cors_headers(event),
                'statusCode': 409,
                'body': json.dumps({'message': error.message}),
            }
        if response.get('statusCode') == 200 and _json_object(response.get('body')).get('pending') is True:
            response['statusCode'] = 202
        return response

    return mapped


def _cors_headers(event) -> dict:
    headers = event.get('headers') or {}
    origin = None
    for key, value in headers.items():
        if str(key).lower() == 'origin':
            origin = value
            break
    allowed = config_module.config.allowed_origins
    chosen = origin if origin in allowed else allowed[0]
    return {'Access-Control-Allow-Origin': chosen, 'Vary': 'Origin'}


def _json_object(body) -> dict:
    if not isinstance(body, str):
        return {}
    try:
        loaded = json.loads(body)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}
