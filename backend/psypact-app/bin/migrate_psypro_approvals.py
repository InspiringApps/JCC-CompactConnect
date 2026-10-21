#!/usr/bin/env python3
"""Invoke the source-query lambda to migrate approved PSYPRO records.

The lambda reads SQL and the Psypro Dynamo tables, then writes the provider
table. This script only starts that action and prints the counts.
"""

import argparse
import json
import logging

import boto3

logger = logging.getLogger(__name__)


def find_query_function(client) -> str:
    paginator = client.get_paginator('list_functions')
    for page in paginator.paginate():
        for function in page['Functions']:
            if 'PsyproSourceQuery' in function['FunctionName']:
                return function['FunctionName']
    raise RuntimeError('PsyproSourceQuery lambda was not found')


def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    parser = argparse.ArgumentParser(description='Migrate approved PSYPRO records into the provider table.')
    parser.add_argument('--region', default='us-east-1')
    parser.add_argument('--write', action='store_true', help='Write the planned items. Omit to return counts only.')
    args = parser.parse_args()

    client = boto3.Session(region_name=args.region).client('lambda')
    function_name = find_query_function(client)
    response = client.invoke(
        FunctionName=function_name,
        Payload=json.dumps({'action': 'migrate', 'dryRun': not args.write}).encode(),
    )
    payload = json.loads(response['Payload'].read())
    if response.get('FunctionError') or 'errorMessage' in payload:
        raise RuntimeError(payload.get('errorMessage', payload))
    logger.info(
        'dryRun=%s users=%s authorizations=%s providers=%s licenses=%s '
        'skippedProviders=%s skippedLicenses=%s wrote=%s',
        payload.get('dryRun'),
        payload.get('users'),
        payload.get('authorizations'),
        payload.get('providers'),
        payload.get('licenses'),
        payload.get('skippedProviders'),
        payload.get('skippedLicenses'),
        payload.get('wrote'),
    )


if __name__ == '__main__':
    main()
