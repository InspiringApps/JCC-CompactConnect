from __future__ import annotations

from common_constructs.stack import AppStack
from constructs import Construct

from stacks import persistent_stack as ps

from .application_workflow import ApplicationWorkflow


class ApplicationWorkflowStack(AppStack):
    """Step Functions workflow that drives one practitioner application execution."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        environment_name: str,
        persistent_stack: ps.PersistentStack,
        **kwargs,
    ):
        super().__init__(scope, construct_id, environment_name=environment_name, **kwargs)

        workflow = ApplicationWorkflow(
            self,
            'ApplicationWorkflow',
            persistent_stack=persistent_stack,
        )
        self.state_machine = workflow.state_machine
        self.enter_state_function = workflow.enter_state_function
        self.schedule_group_name = workflow.schedule_group_name
