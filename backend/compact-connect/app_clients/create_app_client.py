#!/usr/bin/env python3
"""
Script to create AWS Cognito app clients based on YAML configuration files.

This script automates the process of creating app clients in different environments
(test, beta, prod) by reading configuration from YAML files and using boto3
to create the app client with the specified scopes and settings.
"""

import argparse
import json
import os
import sys
import yaml
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from pathlib import Path


def load_yaml_config(environment, yaml_filename):
    """Load and parse the YAML configuration file for the specified environment."""
    # Map environment to directory
    env_dir_map = {
        'test': 'cc_test_app_clients',
        'beta': 'cc_beta_app_clients',
        'prod': 'cc_prod_app_clients'
    }
    
    if environment not in env_dir_map:
        raise ValueError(f"Invalid environment: {environment}. Must be one of: test, beta, prod")
    
    # Get the directory path
    script_dir = Path(__file__).parent
    config_dir = script_dir / env_dir_map[environment]
    config_file = config_dir / yaml_filename
    
    if not config_file.exists():
        raise FileNotFoundError(f"YAML file not found: {config_file}")
    
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
    
    return config


def validate_config(config):
    """Validate that the YAML configuration contains required fields."""
    required_fields = ['clientName', 'scopes']
    
    for field in required_fields:
        if field not in config:
            raise ValueError(f"Missing required field in YAML config: {field}")
    
    if not isinstance(config['scopes'], list) or len(config['scopes']) == 0:
        raise ValueError("'scopes' must be a non-empty list")


def create_app_client(user_pool_id, config):
    """Create the app client using boto3 Cognito client."""
    client_name = config['clientName']
    scopes = config['scopes']
    
    print(f"Creating app client: {client_name}")
    print(f"With scopes: {', '.join(scopes)}")
    
    try:
        # Create boto3 Cognito IDP client
        cognito_client = boto3.client('cognito-idp', region_name='us-east-1')
        
        # Create the user pool client
        response = cognito_client.create_user_pool_client(
            UserPoolId=user_pool_id,
            ClientName=client_name,
            PreventUserExistenceErrors='ENABLED',
            GenerateSecret=True,
            TokenValidityUnits={
                'AccessToken': 'minutes'
            },
            AccessTokenValidity=15,
            AllowedOAuthFlowsUserPoolClient=True,
            AllowedOAuthFlows=['client_credentials'],
            AllowedOAuthScopes=scopes
        )
        
        return response
        
    except NoCredentialsError:
        print("Error: AWS credentials not found. Please configure your AWS credentials.")
        print("You can use 'aws configure' or set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables.")
        sys.exit(1)
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        print(f"Error creating app client: {error_code} - {error_message}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error creating app client: {e}")
        sys.exit(1)


def print_credentials(client_id, client_secret):
    """Print the credentials in JSON format for secure copy/paste."""
    credentials = {
        "clientId": client_id,
        "clientSecret": client_secret
    }
    
    print("APP CLIENT CREDENTIALS\n\n")
    print(json.dumps(credentials, indent=2))
    print("\n\nPlease copy the credentials above and send them to the recipient through a secure channel.")
    print("Do not leave these credentials in terminal history or logs.")


def main():
    parser = argparse.ArgumentParser(
        description='Create AWS Cognito app client from YAML configuration'
    )
    parser.add_argument(
        '-e', '--environment',
        required=True,
        choices=['test', 'beta', 'prod'],
        help='Environment (test, beta, or prod)'
    )
    parser.add_argument(
        '-u', '--user-pool-id',
        required=True,
        help='AWS Cognito User Pool ID'
    )
    parser.add_argument(
        '-f', '--yaml-file',
        required=True,
        help='Name of the YAML configuration file (e.g., example_app_client.yml)'
    )
    
    args = parser.parse_args()
    
    try:
        # Load and validate configuration
        print(f"Loading configuration from {args.yaml_file} for {args.environment} environment...")
        config = load_yaml_config(args.environment, args.yaml_file)
        validate_config(config)
        
        # Create the app client
        response = create_app_client(args.user_pool_id, config)
        
        # Extract credentials from response
        user_pool_client = response.get('UserPoolClient', {})
        client_id = user_pool_client.get('ClientId')
        client_secret = user_pool_client.get('ClientSecret')
        client_name = user_pool_client.get('ClientName')
        
        if not client_id or not client_secret:
            print("Error: Could not extract client ID or secret from AWS response")
            sys.exit(1)
        
        print(f"\nApp client created successfully!")
        print(f"Client Name: {client_name}")
        print(f"Client ID: {client_id}")
        
        # Print credentials for secure copy/paste
        print_credentials(client_id, client_secret)
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main() 
