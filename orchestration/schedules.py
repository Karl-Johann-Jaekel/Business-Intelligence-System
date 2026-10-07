"""Daily schedule: each tick advances the simulation clock by one day and runs the pipeline."""

import os

from dagster import (
    DagsterRunStatus,
    DefaultScheduleStatus,
    JobDefinition,
    RunConfig,
    RunRequest,
    RunsFilter,
    ScheduleEvaluationContext,
    SkipReason,
    schedule,
)

from orchestration.assets import CLOCK_OP_NAME, ClockConfig

# Real deployment: once a day. Demos / fast-forward: e.g. BIS_SCHEDULE_CRON="*/3 * * * *".
SCHEDULE_CRON = os.getenv("BIS_SCHEDULE_CRON", "0 2 * * *")
SCHEDULE_ENABLED = os.getenv("BIS_SCHEDULE_ENABLED", "false").lower() == "true"

# NOT_STARTED is deliberately excluded: a run created but never launched (e.g. a crashed CLI
# call) would otherwise block the schedule forever.
ACTIVE_STATUSES = [
    DagsterRunStatus.QUEUED,
    DagsterRunStatus.STARTING,
    DagsterRunStatus.STARTED,
    DagsterRunStatus.CANCELING,
]


def build_schedule(job: JobDefinition):
    @schedule(
        name="simulated_day",
        job=job,
        cron_schedule=SCHEDULE_CRON,
        default_status=DefaultScheduleStatus.RUNNING if SCHEDULE_ENABLED else DefaultScheduleStatus.STOPPED,
    )
    def simulated_day(context: ScheduleEvaluationContext):
        # Never let two simulated days overlap: the second would read a half-built warehouse.
        active = context.instance.get_run_records(
            filters=RunsFilter(job_name=job.name, statuses=ACTIVE_STATUSES), limit=1
        )
        if active:
            return SkipReason(f"Run {active[0].dagster_run.run_id} for the previous day is still active")
        return RunRequest(
            run_config=RunConfig(ops={CLOCK_OP_NAME: ClockConfig(advance_days=1)}),
            tags={"dagster/max_retries": "2", "dagster/retry_strategy": "FROM_FAILURE"},
        )

    return simulated_day
