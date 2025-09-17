import os
from typing import List, Optional

from aws_cdk import RemovalPolicy, Stack
from aws_cdk import aws_codebuild as codebuild
from aws_cdk import aws_codepipeline as codepipeline
from aws_cdk import aws_codepipeline_actions as codepipeline_actions
from aws_cdk.aws_codestarnotifications import NotificationRule
from aws_cdk.aws_iam import Effect, PolicyStatement, ServicePrincipal
from aws_cdk.aws_kms import IKey
from aws_cdk.aws_s3 import BucketEncryption, IBucket
from aws_cdk.aws_sns import ITopic
from aws_cdk.aws_ssm import IParameter
from cdk_nag import NagSuppressions
from constructs import Construct

from common_constructs.bucket import Bucket


class BackendPipeline(Construct):
    """
    Backend CodePipeline with ONLY tag-based triggers using CodePipeline v2.

    This pipeline is part of a two-pipeline architecture where:
    1. This Backend Pipeline deploys infrastructure and creates required resources
    2. The Frontend Pipeline then deploys the frontend application using those resources

    Tag-Only Deployment Flow:
    - Triggered EXCLUSIVELY by specific Git tag patterns (e.g., test-*, beta-*, prod-*)
    - NO branch-based triggers or manual execution support
    - Uses CodePipeline v2 for advanced trigger configuration
    - Triggers the Frontend Pipeline after successful deployment
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        pipeline_name: str,
        github_repo_string: str,
        cdk_path: str,
        connection_arn: str,
        tag_patterns: List[str],
        excluded_tag_patterns: Optional[List[str]] = None,

        access_logs_bucket: IBucket,
        encryption_key: IKey,
        alarm_topic: ITopic,
        ssm_parameter: IParameter,
        pipeline_stack_name: str,
        environment_context: dict,
        removal_policy: RemovalPolicy,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)
        
        self.pipeline_name = pipeline_name
        self.github_repo_string = github_repo_string
        self.cdk_path = cdk_path
        self.connection_arn = connection_arn
        self.tag_patterns = tag_patterns
        self.excluded_tag_patterns = excluded_tag_patterns or []

        self.encryption_key = encryption_key
        self.alarm_topic = alarm_topic
        self.ssm_parameter = ssm_parameter
        self.pipeline_stack_name = pipeline_stack_name
        self.environment_context = environment_context
        self.removal_policy = removal_policy

        # Create artifact bucket
        self.artifact_bucket = Bucket(
            self,
            f'{construct_id}ArtifactsBucket',
            encryption_key=encryption_key,
            encryption=BucketEncryption.KMS,
            versioned=True,
            server_access_logs_bucket=access_logs_bucket,
            removal_policy=removal_policy,
            auto_delete_objects=removal_policy == RemovalPolicy.DESTROY,
        )
        
        NagSuppressions.add_resource_suppressions(
            self.artifact_bucket,
            suppressions=[
                {
                    'id': 'HIPAA.Security-S3BucketReplicationEnabled',
                    'reason': 'These artifacts are reproduced on deploy, so the resilience from replication is not'
                    ' necessary',
                },
            ],
        )

        # Create artifacts
        self.source_output = codepipeline.Artifact("SourceOutput")
        self.synth_output = codepipeline.Artifact("SynthOutput")

        # Create source action
        self.source_action = codepipeline_actions.CodeStarConnectionsSourceAction(
            action_name="Source",
            owner=github_repo_string.split('/')[0],
            repo=github_repo_string.split('/')[1],
            branch="main",  # Required parameter but not used for tag triggers
            connection_arn=connection_arn,
            output=self.source_output,
        )

        # Create synth action
        self.synth_action = self._create_synth_action()

        # Create the pipeline with tag triggers
        self.pipeline = self._create_pipeline()

        # Add alarms and notifications
        self._add_alarms()

    def _create_synth_action(self) -> codepipeline_actions.CodeBuildAction:
        """Create the CodeBuild action for CDK synthesis"""
        
        # Create CodeBuild project for synthesis
        synth_project = codebuild.Project(
            self,
            "SynthProject",
            build_spec=codebuild.BuildSpec.from_object({
                "version": "0.2",
                "phases": {
                    "install": {
                        "runtime-versions": {
                            "python": "3.12",
                            "nodejs": "22.x"
                        }
                    },
                    "build": {
                        "commands": [
                            f"cd {self.cdk_path}",
                            "npm install -g aws-cdk",
                            "python -m pip install -r requirements.txt",
                            "( cd lambdas/nodejs; yarn install --frozen-lockfile )",
                            f"cdk synth --context pipelineStack={self.pipeline_stack_name} --context action=pipelineSynth",
                        ]
                    }
                },
                "artifacts": {
                    "base-directory": os.path.join(self.cdk_path, "cdk.out"),
                    "files": "**/*"
                }
            }),
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                compute_type=codebuild.ComputeType.SMALL,
            ),
            environment_variables={
                "CDK_DEFAULT_ACCOUNT": codebuild.BuildEnvironmentVariable(
                    value=self.environment_context['account_id']
                ),
                "CDK_DEFAULT_REGION": codebuild.BuildEnvironmentVariable(
                    value=self.environment_context['region']
                ),
            },
            encryption_key=self.encryption_key,
        )

        # Grant SSM parameter read access
        self.ssm_parameter.grant_read(synth_project)

        # Add CDK assume role permissions
        synth_project.add_to_role_policy(
            PolicyStatement(
                effect=Effect.ALLOW,
                actions=['sts:AssumeRole'],
                resources=[
                    Stack.of(self).format_arn(
                        partition=Stack.of(self).partition,
                        service='iam',
                        region='',
                        account='*',
                        resource='role',
                        resource_name='cdk-hnb659fds-lookup-role-*',
                    ),
                ],
            ),
        )

        self.synth_project = synth_project

        return codepipeline_actions.CodeBuildAction(
            action_name="Synth",
            project=synth_project,
            input=self.source_output,
            outputs=[self.synth_output],
        )

    def _create_pipeline(self) -> codepipeline.Pipeline:
        """Create the CodePipeline with tag-based triggers"""
        
        pipeline = codepipeline.Pipeline(
            self,
            "Pipeline",
            pipeline_name=self.pipeline_name,
            pipeline_type=codepipeline.PipelineType.V2,  # Required for triggers
            artifact_bucket=self.artifact_bucket,
            cross_account_keys=True,
            enable_key_rotation=True,
            stages=[
                codepipeline.StageProps(
                    stage_name="Source",
                    actions=[self.source_action],
                ),
                codepipeline.StageProps(
                    stage_name="Synth",
                    actions=[self.synth_action],
                ),
            ],
            triggers=[
                codepipeline.TriggerProps(
                    provider_type=codepipeline.ProviderType.CODE_STAR_SOURCE_CONNECTION,
                    git_configuration=codepipeline.GitConfiguration(
                        source_action=self.source_action,
                        push_filter=[
                            codepipeline.GitPushFilter(
                                tags_includes=self.tag_patterns,
                                tags_excludes=self.excluded_tag_patterns,
                            )
                        ],
                    ),
                )
            ],
        )

        return pipeline

    def add_stage(self, stage_construct, *, pre: Optional[List] = None, post: Optional[List] = None):
        """
        Add a deployment stage to the pipeline.
        
        This method maintains compatibility with the existing CDK Pipelines interface
        while using the lower-level CodePipeline construct.
        
        Note: This is a simplified implementation. In a production environment,
        you would need to implement the full stage conversion logic to handle
        all the stacks and dependencies that the BackendStage contains.
        """
        # Store the stage for later reference
        self.deployment_stage = stage_construct
        
        # For the tag-triggered pipeline, we'll add a simple deploy stage
        # In a full implementation, you would need to:
        # 1. Extract all stacks from the stage_construct
        # 2. Create CloudFormation deploy actions for each stack
        # 3. Handle dependencies between stacks
        # 4. Set up proper IAM roles and permissions
        
        # Simplified deploy action - you'll need to customize this based on your actual stacks
        deploy_actions = []
        
        # Example: If you know the specific stacks in your BackendStage
        # You would create a deploy action for each stack
        stage_name = stage_construct.node.id
        
        # This is a placeholder - replace with actual stack deployment logic
        deploy_action = codepipeline_actions.CloudFormationCreateUpdateStackAction(
            action_name=f"Deploy{stage_name}",
            stack_name=f"{stage_name}Stack",
            template_path=self.synth_output.at_path(f"{stage_name}Stack.template.json"),
            admin_permissions=True,
            # You may need to add more specific parameters here
        )
        
        deploy_actions.append(deploy_action)

        deploy_stage = codepipeline.StageProps(
            stage_name=f"Deploy{stage_name}",
            actions=deploy_actions,
        )

        self.pipeline.add_stage(deploy_stage)

        # Handle post-deployment steps (like triggering frontend pipeline)
        if post:
            post_actions = []
            for step in post:
                if hasattr(step, 'role') and hasattr(step, 'commands'):
                    # This is a CodeBuildStep, convert it to a CodeBuildAction
                    post_action = codepipeline_actions.CodeBuildAction(
                        action_name=step.id,
                        project=codebuild.Project(
                            self,
                            f"{step.id}Project",
                            build_spec=codebuild.BuildSpec.from_object({
                                "version": "0.2",
                                "phases": {
                                    "build": {
                                        "commands": step.commands
                                    }
                                }
                            }),
                            role=step.role,
                            encryption_key=self.encryption_key,
                        ),
                        input=self.synth_output,
                    )
                    post_actions.append(post_action)
            
            if post_actions:
                post_stage = codepipeline.StageProps(
                    stage_name=f"Post{stage_name}",
                    actions=post_actions,
                )
                
                self.pipeline.add_stage(post_stage)



    def _add_alarms(self):
        """Add CloudWatch alarms and notifications"""
        NotificationRule(
            self,
            'NotificationRule',
            source=self.pipeline,
            events=[
                'codepipeline-pipeline-pipeline-execution-started',
                'codepipeline-pipeline-pipeline-execution-failed',
                'codepipeline-pipeline-pipeline-execution-succeeded',
                'codepipeline-pipeline-manual-approval-needed',
            ],
            targets=[self.alarm_topic],
        )

        # Grant CodeStar permission to use the key that encrypts the alarm topic
        code_star_principal = ServicePrincipal('codestar-notifications.amazonaws.com')
        self.encryption_key.grant_encrypt_decrypt(code_star_principal)