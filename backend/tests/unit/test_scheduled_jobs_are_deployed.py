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

import itertools
import re
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


def _api_step() -> str:
    return _step("Deploy the API")


def test_every_run_block_is_valid_shell() -> None:
    """`bash -n` over every step in both workflows.

    A workflow is a YAML file full of shell that nothing type-checks, and the
    failure mode is expensive: you find out after the runner has spun up, and
    for the deploy workflow, after it has already built and pushed an image.

    Catches genuine syntax errors only. It does **not** catch a comment
    interrupting a line continuation -- see the test below, which does; that
    joins into a valid command followed by a comment, and `bash -n` is right
    to accept it. Both checks are here because they fail on different things.
    """
    import re
    import subprocess
    import tempfile

    yaml = pytest.importorskip("yaml")
    root = _repo_root() / ".github" / "workflows"
    if not root.is_dir():
        pytest.skip("no workflows in this checkout")
    if subprocess.run(["bash", "-c", "true"], capture_output=True).returncode:  # noqa: S607
        pytest.skip("no bash available")

    problems: list[str] = []
    for path in sorted(root.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_name, job in (doc.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                script = step.get("run")
                if not script:
                    continue
                # ${{ ... }} is GitHub's template syntax, not shell. Replace it
                # with a plain word so bash parses the shape of the command.
                cleaned = re.sub(r"\$\{\{[^}]*\}\}", "X", script)
                with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as handle:
                    handle.write(cleaned)
                    tmp = handle.name
                result = subprocess.run(  # noqa: S603
                    ["bash", "-n", tmp],  # noqa: S607
                    capture_output=True,
                    text=True,
                )
                Path(tmp).unlink(missing_ok=True)
                if result.returncode:
                    label = step.get("name", "<unnamed>")
                    problems.append(f"{path.name} / {job_name} / {label}: {result.stderr.strip()}")

    assert not problems, "shell syntax errors in workflow steps:\n" + "\n".join(problems)


def test_no_comment_interrupts_a_line_continuation() -> None:
    """A `#` line after a line ending in `\\` silently truncates the command.

    The continuation joins the two lines, so everything from the `#` to the
    end of the logical line -- including every remaining argument -- becomes a
    comment. `gcloud run deploy interview-api --image X` with its
    --set-secrets and --quiet eaten still *runs*; it just deploys something
    other than what the file appears to say.

    This is not hypothetical. I did exactly this while adding the storage
    variables, and it survived both YAML parsing and `bash -n`, which is why
    it needs a check of its own rather than being folded into the one above.
    """
    yaml = pytest.importorskip("yaml")
    root = _repo_root() / ".github" / "workflows"
    if not root.is_dir():
        pytest.skip("no workflows in this checkout")

    problems: list[str] = []
    for path in sorted(root.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_name, job in (doc.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                lines = (step.get("run") or "").splitlines()
                for prev, nxt in itertools.pairwise(lines):
                    if prev.rstrip().endswith("\\") and nxt.lstrip().startswith("#"):
                        label = step.get("name", "<unnamed>")
                        problems.append(
                            f"{path.name} / {job_name} / {label}: "
                            f"{nxt.strip()[:60]!r} follows a line continuation"
                        )

    assert not problems, (
        "a comment after a `\\` swallows the rest of the command:\n" + "\n".join(problems)
    )


def test_no_setting_with_a_localhost_default_is_left_at_it() -> None:
    """Any default pointing at a dev service must be overridden by the deploy.

    `S3_ENDPOINT_URL` and `S3_PUBLIC_ENDPOINT_URL` both default to
    ``http://localhost:9000`` -- the MinIO in docker-compose -- and the deploy
    set neither. Nothing failed at boot: the API would have started happily
    and signed upload URLs pointing at the user's own laptop, so the first
    symptom would have been a resume upload that hung.

    Derived from the settings model rather than a hand-kept list, so a new
    setting with a localhost default is caught the day it is added.
    """
    from app.core.config import Settings

    step = _api_step()
    missed = [
        name.upper()
        for name, field in Settings.model_fields.items()
        if isinstance(field.default, str) and "localhost" in field.default
        and name.upper() not in step
    ]
    assert not missed, (
        f"these default to a local dev service and the deploy never overrides "
        f"them: {missed}"
    )


def test_the_session_cookie_survives_a_cross_site_request() -> None:
    """The UI and the API are on different sites in production.

    A `lax` cookie is simply not sent on a cross-site request, so every call
    would arrive anonymous -- a total auth failure that no test touching only
    the API can see, because curl has no same-site policy. `none` restores it,
    and browsers drop a `none` cookie that is not also Secure, so the two are
    one setting wearing two names.
    """
    step = _api_step()
    assert "AUTH_COOKIE_SAMESITE=none" in step, (
        "without SameSite=none the browser withholds the session cookie from "
        "every cross-site API call and nobody can log in"
    )
    assert "AUTH_COOKIE_SECURE=true" in step, (
        "a SameSite=none cookie is discarded unless it is also Secure"
    )


def test_the_scheduled_jobs_can_reach_object_storage() -> None:
    """Retention deletes objects, so it needs the same storage config as the API.

    Easy to miss because the job would run, report success, and delete the
    database rows -- leaving the files it was supposed to purge sitting in the
    bucket. A retention job that half works is worse than one that fails.
    """
    step = _step("Deploy the scheduled jobs")
    assert "S3_ENDPOINT_URL" in step or "COMMON_STORAGE" in step, (
        "the retention job has no storage endpoint and would silently fail to "
        "delete the files it exists to delete"
    )


def test_the_deploy_needs_nothing_configured_in_the_repo_settings() -> None:
    """No `${{ secrets.* }}` in the deploy workflow.

    The first version needed ten repository secrets before it could run once.
    None of them was a credential -- a project id, a region, a service-account
    email, a Workload Identity path, a bucket name and two public URLs are
    addresses. Storing addresses in a secrets page bought nothing and cost a
    setup step that fails late and only for whoever forgot one of the ten.

    They are literals now, so a fresh clone deploys with no console setup at
    all. This test stops them drifting back: a `${{ secrets.X }}` here is a
    hidden prerequisite, and the first sign of it is a deploy that fails after
    building and pushing an image.

    Real credentials are unaffected -- they live in Google Secret Manager and
    are named by `--set-secrets`, which resolves them at runtime inside Cloud
    Run and never passes them through GitHub.
    """
    if not DEPLOY.is_file():
        pytest.skip("deploy.yml not present in this checkout")
    text = DEPLOY.read_text(encoding="utf-8")
    found = re.findall(r"\$\{\{\s*secrets\.([A-Za-z_][A-Za-z0-9_]*)", text)
    assert not found, (
        f"deploy.yml requires repository secrets that must be set by hand: "
        f"{sorted(set(found))}. If one is a real credential it belongs in "
        f"Secret Manager via --set-secrets; if it is an address, inline it."
    )


def test_the_auth_step_still_has_both_halves() -> None:
    """Guards the test above from passing by deleting the auth instead.

    Removing `${{ secrets.* }}` satisfies the previous assertion whether the
    values were inlined or the authentication step was dropped, and only one
    of those deploys anything.
    """
    if not DEPLOY.is_file():
        pytest.skip("deploy.yml not present in this checkout")
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(DEPLOY.read_text(encoding="utf-8"))
    env = doc.get("env") or {}
    assert "workloadIdentityPools" in str(env.get("GCP_WIF_PROVIDER", "")), (
        "no Workload Identity provider -- the deploy cannot authenticate to GCP"
    )
    assert str(env.get("GCP_SERVICE_ACCOUNT", "")).endswith(".iam.gserviceaccount.com"), (
        "no service account to impersonate"
    )


def test_every_cloud_run_deploy_names_a_runtime_service_account() -> None:
    """Omitting `--service-account` silently picks the worst possible identity.

    Cloud Run defaults to ``NNN-compute@developer.gserviceaccount.com``, which
    carries ``roles/editor`` on the whole project -- so a container running as
    it can do nearly anything to your infrastructure. It also, despite that,
    cannot read Secret Manager payloads, so the first real deploy died at job
    creation with "Permission denied on secret ... for Revision service
    account", which reads like the *deployer* lacks access when the deployer
    has it and is not the account being complained about.

    Both problems have one fix: name a runtime account that can read secrets
    and do nothing else. This asserts every deploy does.
    """
    if not DEPLOY.is_file():
        pytest.skip("deploy.yml not present in this checkout")
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(DEPLOY.read_text(encoding="utf-8"))

    missing: list[str] = []
    for step in doc["jobs"]["backend"]["steps"]:
        script = step.get("run") or ""
        # Each `gcloud run [jobs] deploy` and its continued lines form one
        # logical command; split on the deploy verb and check each fragment.
        for fragment in re.split(r"gcloud run (?:jobs )?deploy", script)[1:]:
            command = fragment.split("--quiet")[0]
            if "--service-account" not in command:
                missing.append(f"{step.get('name', '?')}: {command.strip()[:60]}")
    assert not missing, (
        "these Cloud Run deploys fall back to the default compute service "
        f"account (roles/editor, and no secret access): {missing}"
    )


def test_the_runtime_account_is_not_the_deployer() -> None:
    """They must be different identities, or least privilege buys nothing.

    The deployer holds run.admin and can redeploy the service. An application
    that runs as its own deployer is one compromise away from being permanent.
    """
    if not DEPLOY.is_file():
        pytest.skip("deploy.yml not present in this checkout")
    yaml = pytest.importorskip("yaml")
    env = yaml.safe_load(DEPLOY.read_text(encoding="utf-8")).get("env") or {}
    deployer = env.get("GCP_SERVICE_ACCOUNT")
    runtime = env.get("GCP_RUNTIME_SA")
    assert runtime, "no runtime service account is defined"
    assert runtime != deployer, (
        "the app would run as the account that deploys it, so anything that "
        "compromises the app can redeploy the app"
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
