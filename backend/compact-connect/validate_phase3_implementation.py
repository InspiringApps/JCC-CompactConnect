#!/usr/bin/env python3
"""
Phase 3 Implementation Validation Script

This script validates that Phase 3 of the data retention implementation has been
completed correctly by checking file existence, code structure, and configuration.
"""

import json
import os
import re
import sys
from pathlib import Path


def validate_file_exists(file_path: str, description: str) -> bool:
    """Validate that a file exists."""
    if os.path.exists(file_path):
        print(f"✅ {description}: {file_path}")
        return True
    else:
        print(f"❌ {description}: {file_path} (MISSING)")
        return False


def validate_file_contains(file_path: str, pattern: str, description: str) -> bool:
    """Validate that a file contains specific content."""
    if not os.path.exists(file_path):
        print(f"❌ {description}: {file_path} (FILE MISSING)")
        return False
    
    try:
        with open(file_path, 'r') as f:
            content = f.read()
            if re.search(pattern, content, re.MULTILINE | re.DOTALL):
                print(f"✅ {description}: Found in {file_path}")
                return True
            else:
                print(f"❌ {description}: Pattern not found in {file_path}")
                return False
    except Exception as e:
        print(f"❌ {description}: Error reading {file_path}: {e}")
        return False


def validate_json_config(file_path: str, key_path: list, description: str) -> bool:
    """Validate that JSON configuration contains specific keys."""
    if not os.path.exists(file_path):
        print(f"❌ {description}: {file_path} (FILE MISSING)")
        return False
    
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
            
        current = data
        for key in key_path:
            if key in current:
                current = current[key]
            else:
                print(f"❌ {description}: Key path {'.'.join(key_path)} not found in {file_path}")
                return False
        
        print(f"✅ {description}: Configuration found in {file_path}")
        return True
    except Exception as e:
        print(f"❌ {description}: Error reading {file_path}: {e}")
        return False


def main():
    """Main validation function."""
    print("🔍 Validating Phase 3 Data Retention Implementation\n")
    
    validation_results = []
    
    # 1. Validate core infrastructure files
    print("📁 Core Infrastructure Files:")
    validation_results.append(validate_file_exists(
        "stacks/backup_infrastructure_stack.py",
        "Backup Infrastructure Stack"
    ))
    validation_results.append(validate_file_exists(
        "common_constructs/backup_plan.py", 
        "Backup Plan Construct"
    ))
    
    # 2. Validate S3 bucket backup implementation
    print("\n📦 S3 Bucket Backup Implementation:")
    validation_results.append(validate_file_contains(
        "stacks/persistent_stack/provider_users_bucket.py",
        r"from common_constructs\.backup_plan import BackupPlanConstruct",
        "ProviderUsersBucket imports BackupPlanConstruct"
    ))
    validation_results.append(validate_file_contains(
        "stacks/persistent_stack/provider_users_bucket.py",
        r"def _implement_backup\(self\)",
        "ProviderUsersBucket implements backup method"
    ))
    validation_results.append(validate_file_contains(
        "stacks/persistent_stack/provider_users_bucket.py",
        r"backup_category='document_storage'",
        "ProviderUsersBucket uses document_storage category"
    ))
    
    # 3. Validate backend stage integration
    print("\n🏗️ Backend Stage Integration:")
    validation_results.append(validate_file_contains(
        "pipeline/backend_stage.py",
        r"from stacks\.backup_infrastructure_stack import BackupInfrastructureStack",
        "BackendStage imports BackupInfrastructureStack"
    ))
    validation_results.append(validate_file_contains(
        "pipeline/backend_stage.py",
        r"self\.backup_infrastructure_stack = BackupInfrastructureStack",
        "BackendStage creates backup infrastructure"
    ))
    validation_results.append(validate_file_contains(
        "pipeline/backend_stage.py",
        r"backup_infrastructure=self\.backup_infrastructure_stack",
        "BackendStage passes backup infrastructure to PersistentStack"
    ))
    
    # 4. Validate configuration
    print("\n⚙️ Configuration:")
    validation_results.append(validate_json_config(
        "cdk.json",
        ["context", "backup_config"],
        "Backup configuration in CDK context"
    ))
    validation_results.append(validate_json_config(
        "cdk.json",
        ["context", "backup_policies", "document_storage"],
        "Document storage backup policy"
    ))
    validation_results.append(validate_json_config(
        "cdk.json",
        ["context", "backup_policies", "critical_data"],
        "Critical data backup policy"
    ))
    
    # 5. Validate exclusion criteria implementation
    print("\n🚫 Backup Exclusion Verification:")
    validation_results.append(validate_file_contains(
        "stacks/persistent_stack/bulk_uploads_bucket.py",
        r"'reason': 'This bucket houses transitory data only",
        "BulkUploadsBucket correctly excluded (transitory data)"
    ))
    validation_results.append(validate_file_contains(
        "stacks/persistent_stack/transaction_reports_bucket.py",
        r"'reason': 'This bucket is used to store read-only reports that can be regenerated",
        "TransactionReportsBucket correctly excluded (derived data)"
    ))
    
    # 6. Validate test files
    print("\n🧪 Test Implementation:")
    validation_results.append(validate_file_exists(
        "tests/common_constructs/test_backup_plan.py",
        "Backup Plan Construct Tests"
    ))
    validation_results.append(validate_file_exists(
        "tests/stacks/test_backup_infrastructure_stack.py",
        "Backup Infrastructure Stack Tests"
    ))
    validation_results.append(validate_file_exists(
        "tests/stacks/persistent_stack/test_provider_users_bucket_backup.py",
        "Provider Users Bucket Backup Tests"
    ))
    
    # 7. Validate documentation
    print("\n📚 Documentation:")
    validation_results.append(validate_file_exists(
        "docs/phase3-s3-backup-criteria.md",
        "Phase 3 S3 Backup Criteria Documentation"
    ))
    validation_results.append(validate_file_exists(
        "docs/phase3-implementation-summary.md",
        "Phase 3 Implementation Summary"
    ))
    
    # 8. Validate persistent stack updates
    print("\n🏛️ Persistent Stack Updates:")
    validation_results.append(validate_file_contains(
        "stacks/persistent_stack/__init__.py",
        r"backup_infrastructure=None",
        "PersistentStack accepts backup_infrastructure parameter"
    ))
    validation_results.append(validate_file_contains(
        "stacks/persistent_stack/__init__.py",
        r"self\.backup_infrastructure = backup_infrastructure",
        "PersistentStack stores backup_infrastructure"
    ))
    
    # Summary
    print(f"\n📊 Validation Summary:")
    passed = sum(validation_results)
    total = len(validation_results)
    print(f"Passed: {passed}/{total} validations")
    
    if passed == total:
        print("🎉 Phase 3 implementation validation PASSED!")
        print("✅ All required components are implemented correctly.")
        return 0
    else:
        print("❌ Phase 3 implementation validation FAILED!")
        print(f"❌ {total - passed} validation(s) failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())