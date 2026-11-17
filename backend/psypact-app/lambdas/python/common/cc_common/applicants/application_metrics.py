"""Count metrics the application workflow alarms on."""

from aws_lambda_powertools.metrics import MetricUnit

from cc_common.config import metrics


def emit_count(name: str) -> None:
    """Record one occurrence of ``name`` for the compact-connect metric namespace."""
    metrics.add_metric(name=name, unit=MetricUnit.Count, value=1)
