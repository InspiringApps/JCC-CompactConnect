# Tag-Triggered Pipeline Full Conversion

This document explains the complete conversion from branch-based pipeline triggers to tag-based pipeline triggers.

## What Was Changed

The `BackendPipeline` class has been **completely converted** from using the high-level CDK Pipelines construct to using the lower-level CodePipeline v2 construct with tag-based triggers. This is a full conversion with no alternative implementations.

### Key Changes Made:

1. **`backend_pipeline.py`**: Completely rewritten to use CodePipeline v2 with tag triggers
2. **Pipeline Stack Classes**: Updated to use tag patterns instead of branch triggers
3. **Interface Compatibility**: Maintained the same public interface for seamless migration

## New Tag-Based Trigger Strategy

- **Test Environment**: Triggered by tags matching `test-*` (e.g., `test-v1.2.3`, `test-hotfix-123`)
- **Beta Environment**: Triggered by tags matching `beta-*` (e.g., `beta-v1.2.3`, `beta-rc1`)
- **Production Environment**: Triggered by tags matching `prod-*` (e.g., `prod-v1.2.3`, `prod-hotfix-123`)

### Excluded Patterns

Each environment excludes certain tag patterns to prevent accidental deployments:
- `*-draft` - Draft versions
- `*-wip` - Work in progress
- `prod-*-beta` - Beta tags in production (additional safety)

## Benefits of the Conversion

1. **Precise Version Control**: Deploy specific versions to specific environments
2. **No Accidental Deployments**: Branch pushes no longer trigger deployments
3. **Clear Audit Trail**: Easy to see what version is deployed where
4. **Hotfix Support**: Deploy urgent fixes with specific version tags
5. **GitHub Integration**: Use familiar GitHub release workflow

## New Deployment Workflow

### Using GitHub Releases (Recommended)

1. **Develop and merge** your changes to the main branch
2. **Create releases** in GitHub UI with appropriate tags:
   - Go to GitHub → Releases → Create a new release
   - Enter tag name (e.g., `test-v1.2.3`)
   - Add release notes
   - Publish release

### Tag Naming Examples

#### Test Environment
- `test-v1.2.3` - Standard test release
- `test-feature-auth` - Feature-specific test
- `test-hotfix-123` - Hotfix release

#### Beta Environment
- `beta-v1.2.3` - Beta release candidate
- `beta-v1.2.3-rc1` - Release candidate 1
- `beta-hotfix-123` - Beta hotfix

#### Production Environment
- `prod-v1.2.3` - Production release
- `prod-v1.2.3-hotfix` - Production hotfix
- `prod-rollback-v1.2.2` - Rollback to previous version

## Implementation Details

### BackendPipeline Class Changes

The `BackendPipeline` class now:
- Inherits from `Construct` instead of `CdkCodePipeline`
- Uses `codepipeline.Pipeline` with `PipelineType.V2`
- Configures `GitConfiguration` with tag-based triggers
- Maintains the same public interface (`add_stage`, `build_pipeline`)

### Pipeline Stack Updates

All three pipeline stacks now use tag patterns:

```python
# Test Environment
tag_patterns=['test-*']
excluded_tag_patterns=['test-*-draft', 'test-*-wip']

# Beta Environment  
tag_patterns=['beta-*']
excluded_tag_patterns=['beta-*-draft', 'beta-*-wip']

# Production Environment
tag_patterns=['prod-*']
excluded_tag_patterns=['prod-*-draft', 'prod-*-wip', 'prod-*-beta']
```

## Deployment Process

### 1. Deploy the Updated Pipeline Infrastructure

```bash
cdk deploy --context action=bootstrapDeploy
```

This will update your existing pipelines to use tag-based triggers.

### 2. Test the New Trigger System

Create test releases to verify the new trigger system:

1. Create a release with tag `test-migration-test`
2. Verify the test pipeline triggers
3. Check that no other pipelines are triggered

### 3. Update Your Team's Workflow

- **Stop pushing to trigger deployments**: Branch pushes no longer trigger deployments
- **Use GitHub releases**: Create releases with appropriate tags to trigger deployments
- **Follow naming conventions**: Use the established tag patterns for each environment

## Monitoring and Troubleshooting

### Verify Pipeline Triggers

Check pipeline execution history to see trigger sources:

```bash
aws codepipeline list-pipeline-executions --pipeline-name test-compactConnect-backendPipeline
```

Look for the trigger type in the execution details.

### Common Issues

1. **Pipeline not triggering**: Verify tag patterns match exactly
2. **Wrong environment triggered**: Check tag naming convention
3. **Permission errors**: Ensure CodeStar connection has proper permissions

## Rollback (If Needed)

If you need to rollback to branch-based triggers, you would need to:

1. Revert the `BackendPipeline` class to use CDK Pipelines
2. Update pipeline stacks to use `trigger_branch` instead of `tag_patterns`
3. Redeploy the pipeline infrastructure

However, this conversion is designed to be a permanent improvement to your deployment process.

## Best Practices

1. **Use semantic versioning**: `v1.2.3` format for clear version tracking
2. **Environment prefixes**: Always prefix tags with environment name
3. **Test first**: Always deploy to test environment first
4. **Document releases**: Use GitHub release notes to document changes
5. **Clean up old releases**: Regularly clean up old/unused releases

## Example Workflow

```bash
# 1. Develop feature
git checkout -b feature/new-auth
# ... make changes ...
git commit -m "Add new authentication feature"

# 2. Merge to main
git checkout main
git merge feature/new-auth
git push origin main  # No deployments triggered!

# 3. Deploy to test (via GitHub UI)
# Create release with tag: test-v1.2.3

# 4. After testing, deploy to beta (via GitHub UI)  
# Create release with tag: beta-v1.2.3

# 5. After validation, deploy to production (via GitHub UI)
# Create release with tag: prod-v1.2.3
```

This new workflow provides much more control and prevents accidental deployments while maintaining all the functionality of your existing pipeline architecture.