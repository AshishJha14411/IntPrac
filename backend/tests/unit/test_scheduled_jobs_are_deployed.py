"""Every scheduled job must actually be scheduled somewhere that runs it.

This is the third instance of one bug in this codebase, so it gets a test
rather than another comment:

* ``CELERY_TASK_ALWAYS_EAGER`` was set in a console and nowhere in the repo.
* ``LLM_GRADER_MODEL`` had a cheap default in ``config.py`` that compose
  silently overrode, so the measured saving was never live.
* ``app/entrypoints/jobs.py`` was written specifically because workerless mode
  (ADR 010) deletes beat and takes retention with it -- and then nothing in
  ``deploy.yml`` invoked it. The six-month retention window was enforced by a
  docstring.

In all three the code was right and the running system did not have it. Unit
tests cannot see a running system, but they can see the deployment
*description*, and that is where the omission lives. So: enumerate the jobs
from the entrypoint itself, then require the deploy workflow to both build and
schedule each one. Adding a job without wiring it up now fails here.

Deliberately string matching against the YAML rather than importing gcloud's
semantics. The point is to catch "nobody wired this up at all", which a crude
check catches perfectly well; a sophisticated one would mostly add ways for
the test itself to be wrong.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.entrypoints.jobs import JOBS


def _repo_root() -> Path:
    """Mounted read-only at /repo by the compose ``test`` service."""
    mounted = Path("/repo")
    if (mounted / ".github").is_dir():
        return mounted
    return Path(__file__).resolve().parents[3]


DEPLOY = _repo_root() / ".github" / "workflows" / "deploy.yml"


def _step(name: str) -> str:
    """The shell script of one named step in the `backend` deploy job.

    Reading the step rather than the whole file matters: a job name appears in
    both the build step and the schedule step, so searching the file as a
    whole would let either one alone satisfy both tests.
    """
    if not DEPLOY.is_file():
        pytest.skip(f"{DEPLOY} not present in this checkout")
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(DEPLOY.read_text(encoding="utf-8"))
    for step in doc["jobs"]["backend"]["steps"]:
        if step.get("name") == name:
            return str(step.get("run", ""))
    raise AssertionError(f"deploy.yml has no step named {name!r}")


def _live_lines(script: str) -> list[str]:
    """Shell lines that actually execute -- comments stripped.

    Not pedantry. The first version of this file searched the raw step text
    for the job name, and commenting a schedule out left the name sitting in
    the comment, so the test happily passed on a deployment that no longer
    scheduled anything. A guard against silent omission has to ignore exactly
    the text that makes an omission silent.
    """
    out = []
    for raw in script.splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


@pytest.fixture(scope="module")
def built_jobs() -> set[str]:
    """Job names the build step really loops over."""
    jobs: set[str] = set()
    for line in _live_lines(_step("Deploy the scheduled jobs")):
        if line.startswith("for job in ") and line.endswith("; do"):
            jobs |= set(line[len("for job in ") : -len("; do")].split())
    return jobs


@pytest.fixture(scope="module")
def scheduled_targets() -> set[str]:
    """Cloud Run Job names really passed to a `schedule` call.

    Each call is `schedule <scheduler-name> "<cron>" <cloud-run-job>`, so the
    target is the last field.
    """
    targets: set[str] = set()
    for line in _live_lines(_step("Schedule them")):
        if line.startswith("schedule ") and not line.startswith("schedule()"):
            parts = line.split()
            if len(parts) >= 4:
                targets.add(parts[-1])
    return targets


def test_the_entrypoint_exposes_the_jobs_we_think_it_does() -> None:
    """Guards the tests below: if JOBS were empty they would pass vacuously."""
    assert set(JOBS) >= {"retention", "drain"}


@pytest.mark.parametrize("job", sorted(JOBS))
def test_each_job_is_built_as_a_cloud_run_job(job: str, built_jobs: set[str]) -> None:
    """A job nothing deploys cannot run, however correct its code is."""
    assert job in built_jobs, (
        f"deploy.yml's build step never creates a Cloud Run Job for '{job}' "
        f"(it builds: {sorted(built_jobs) or 'nothing'})"
    )


@pytest.mark.parametrize("job", sorted(JOBS))
def test_each_job_has_a_schedule(job: str, scheduled_targets: set[str]) -> None:
    """A job deployed but never triggered is the exact bug this file exists for.

    Cloud Run Jobs do not run themselves. Without a Cloud Scheduler entry the
    job sits in the console looking deployed, having never once executed --
    which is indistinguishable, at a glance, from working.
    """
    assert f"interview-{job}" in scheduled_targets, (
        f"'{job}' is deployed but nothing ever triggers it "
        f"(scheduled: {sorted(scheduled_targets) or 'nothing'})"
    )


def test_the_build_step_invokes_the_entrypoint() -> None:
    """The Cloud Run Job must run our job runner, not some other command."""
    script = _step("Deploy the scheduled jobs")
    assert "gcloud run jobs deploy" in script
    assert "app.entrypoints.jobs" in script


def test_no_worker_or_beat_service_is_deployed() -> None:
    """ADR 010's cost model, asserted rather than assumed.

    A polling worker cannot scale to zero, so deploying one would quietly
    reintroduce a bill that is there whether anyone interviews or not. Cloud
    Run *Jobs* are fine -- they exit. A Cloud Run *service* named worker or
    beat is not.
    """
    if not DEPLOY.is_file():
        pytest.skip("deploy.yml not present in this checkout")
    text = DEPLOY.read_text(encoding="utf-8")
    for forbidden in ("gcloud run deploy interview-worker", "gcloud run deploy interview-beat"):
        assert forbidden not in text, (
            f"{forbidden!r} would run continuously; workerless mode (ADR 010) "
            "exists precisely to avoid that cost"
        )


def test_the_api_service_can_scale_to_zero() -> None:
    """`--min-instances 0` is not a tuning knob here, it is the cost model."""
    if not DEPLOY.is_file():
        pytest.skip("deploy.yml not present in this checkout")
    text = DEPLOY.read_text(encoding="utf-8")
    assert "--min-instances 0" in text, (
        "the API must scale to zero; a warm instance is billed around the "
        "clock and this app is idle almost all of it"
    )
