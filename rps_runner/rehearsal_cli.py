"""Explicit real-path release rehearsal for a sixteen-Team Tournament."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import select
import subprocess
import sys
import time
from typing import Any, Callable, Mapping, Optional, TextIO
from urllib.parse import quote
from urllib.request import urlopen

from rps_runner.artifact_store import resolve_artifact
from rps_runner.batch_plan_cli import main as batch_plan_main
from rps_runner.engine.container_session import CONTAINER_ISOLATION_PROFILE_VERSION
from rps_runner.execution_profile import INITIAL_EXECUTION_PROFILE
from rps_runner.host_readiness import (
    HostReadinessRequest,
    REHEARSAL_REPORT_FORMAT_VERSION,
    diagnose_host_readiness,
)
from rps_runner.language_environment import load_catalog
from rps_runner.tournament.plan import validate_tournament_plan
from rps_runner.tournament.runner import SCHEDULED_TURNS_PER_MATCH
from rps_runner.tournament.state import fold_tournament_state
from rps_runner.tournament.storage import (
    load_competition_records,
    load_manifest,
    load_operational_telemetry,
    load_scoreboard_projection,
)


OBJECTIVE_SECONDS = 40 * 60
TIMING_OBJECTIVE_EXIT_CODE = 1
CORRECTNESS_FAILURE_EXIT_CODE = 2
TEAM_COUNT = 16
MATCH_PARALLELISM = 4
EXPECTED_FIXTURES = 123
EXPECTED_MATCHES = 369


@dataclass(frozen=True)
class RehearsalOperations:
    """Replaceable system boundaries used by the real public rehearsal command."""

    inspect_configuration: Callable[[HostReadinessRequest], Mapping[str, Any]]
    inspect_target_machine: Callable[[], Mapping[str, Any]]
    run_batch: Callable[[list[str]], int]
    review_plan: Callable[[Path, Path, Path], Mapping[str, Any]]
    approve_plan: Callable[[Mapping[str, Any], TextIO], bool]
    prove_archive_restore: Callable[[Path, Path], Mapping[str, Any]]
    run_tournament: Callable[[list[str]], Mapping[str, Any]]
    rehearse_presentation: Callable[[Path], Mapping[str, Any]]
    verify_tournament: Callable[[Path], Mapping[str, Any]]


def _run_batch(arguments: list[str]) -> int:
    return batch_plan_main(arguments, stdout=io.StringIO(), stderr=sys.stderr)


def _runner_control_arguments(arguments: list[str], control: str) -> list[str]:
    retained: list[str] = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--plan":
            index += 2
            continue
        if argument in ("--continuous", "--start", "--resume", "--request-pause"):
            index += 1
            continue
        retained.append(argument)
        index += 1
    return [*retained, control]


def _run_tournament(arguments: list[str]) -> Mapping[str, Any]:
    """Run, pause, and resume the public Runner as an independent process."""

    directory = Path(arguments[arguments.index("--directory") + 1])
    command = [sys.executable, "-m", "rps_runner.tournament_cli", *arguments]
    runner = subprocess.Popen(command)
    observed: list[str] = []
    try:
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if runner.poll() is not None:
                return {
                    "exit_code": int(runner.returncode or 0),
                    "separate_process": True,
                    "interrupted": False,
                    "resumed": False,
                    "states_observed": observed,
                }
            projection = load_scoreboard_projection(directory)
            records_directory = directory / "records"
            has_record = records_directory.is_dir() and any(
                records_directory.glob("*.json")
            )
            if projection is not None and projection.get("status") == "running":
                if "running" not in observed:
                    observed.append("running")
                if has_record:
                    break
            time.sleep(0.25)
        else:
            raise RuntimeError("Runner did not reach an interruptible Match boundary")

        presentation_while_running = _exercise_presentation_while_runner_active(
            directory, runner
        )

        pause = subprocess.run(
            [
                sys.executable,
                "-m",
                "rps_runner.tournament_cli",
                *_runner_control_arguments(arguments, "--request-pause"),
            ],
            check=False,
        )
        if pause.returncode != 0:
            raise RuntimeError("public Runner pause request failed")
        if runner.wait(timeout=300) != 0:
            raise RuntimeError("interrupted public Runner exited non-zero")
        paused = load_scoreboard_projection(directory)
        if paused is None or paused.get("status") != "paused":
            raise RuntimeError("public Runner did not pause at a Match boundary")
        observed.append("paused")

        resumed = subprocess.run(
            [
                sys.executable,
                "-m",
                "rps_runner.tournament_cli",
                *_runner_control_arguments(arguments, "--resume"),
            ],
            check=False,
        )
        final = load_scoreboard_projection(directory)
        final_status = None if final is None else str(final.get("status"))
        if final_status is not None:
            observed.append(final_status)
        resumed_successfully = resumed.returncode == 0 and final_status == "complete"
        return {
            "exit_code": 0 if resumed_successfully else CORRECTNESS_FAILURE_EXIT_CODE,
            "separate_process": True,
            "interrupted": True,
            "resumed": resumed_successfully,
            "states_observed": observed,
            "presentation_while_runner_active": presentation_while_running,
        }
    finally:
        if runner.poll() is None:
            _stop_process(runner)


def _competitive_snapshot(directory: Path) -> Mapping[str, Any]:
    manifest = load_manifest(directory).manifest
    records = load_competition_records(directory)
    state = fold_tournament_state(manifest, records)
    record_bytes = {
        str(path.relative_to(directory)): path.read_bytes()
        for path in (
            directory / "records.index.json",
            *sorted((directory / "records").glob("*.json")),
        )
    }
    return {
        "record_bytes": record_bytes,
        "projection_bytes": (directory / "scoreboard.json").read_bytes(),
        "state": state,
        "champion": state.champion_team_id,
    }


def _stop_process(process: subprocess.Popen[Any]) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _start_presentation_process(directory: Path) -> tuple[subprocess.Popen[str], str]:
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "rps_runner.tournament_cli",
            "present",
            "--directory",
            str(directory),
            "--port",
            "0",
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    ready, _write, _errors = select.select([process.stdout], [], [], 10)
    if not ready:
        _stop_process(process)
        raise RuntimeError("presentation process did not print its loopback URL")
    url = process.stdout.readline().strip()
    if not url.startswith("http://"):
        _stop_process(process)
        raise RuntimeError("presentation process printed an invalid loopback URL")
    return process, url


def _read_live(url: str) -> Mapping[str, Any]:
    with urlopen(url + "api/live", timeout=10) as response:
        if response.status != 200:
            raise RuntimeError("presentation live read failed")
        value = json.loads(response.read())
    if not isinstance(value, dict):
        raise RuntimeError("presentation live response was invalid")
    return value


def _exercise_presentation_while_runner_active(
    directory: Path, runner: subprocess.Popen[Any]
) -> Mapping[str, Any]:
    for operation in ("initial_read", "restart_read"):
        process, url = _start_presentation_process(directory)
        try:
            _read_live(url)
        finally:
            _stop_process(process)
        if runner.poll() is not None:
            raise RuntimeError(
                "presentation interruption did not leave the Runner active"
            )
    return {
        "separate_process": True,
        "interrupted": True,
        "resumed": True,
        "runner_remained_active": True,
        "operations": ["initial_read", "restart_read"],
    }


def _write_scenario_projection(directory: Path, projection: Mapping[str, Any]) -> None:
    replacement = directory / ".scoreboard.next"
    replacement.write_text(json.dumps(projection), encoding="utf-8")
    replacement.replace(directory / "scoreboard.json")


def _rehearse_presentation_lifecycle(
    tournament_directory: Path, final_projection: Mapping[str, Any], match_id: str
) -> Mapping[str, Any]:
    scenario_directory = tournament_directory.parent / "presentation-event-scenarios"
    scenario_directory.mkdir()
    qualifying = json.loads(json.dumps(final_projection))
    qualifying.update(status="running", phase="qualifying", champion=None)
    qualifying.pop("bracket", None)
    qualifying.pop("completion_reason", None)
    qualifying.pop("security_review", None)
    _write_scenario_projection(scenario_directory, qualifying)

    process, url = _start_presentation_process(scenario_directory)
    try:
        observed: list[str] = []
        qualifying_view = _read_live(url)["tournament"]
        observed.append(str(qualifying_view["status"]))
        qualifying_phase = str(qualifying_view["phase"])

        playoff = json.loads(json.dumps(final_projection))
        playoff.update(status="running", phase="playoff", champion=None)
        playoff.pop("completion_reason", None)
        _write_scenario_projection(scenario_directory, playoff)
        playoff_view = _read_live(url)["tournament"]
        observed.append(str(playoff_view["status"]))
        playoff_phase = str(playoff_view["phase"])

        pending = json.loads(json.dumps(playoff))
        pending["status"] = "awaiting_security_ruling"
        pending["security_review"] = {
            "fixture_id": str(pending["fixtures"][0]["fixture_id"]),
            "match_id": match_id,
        }
        _write_scenario_projection(scenario_directory, pending)
        observed.append(str(_read_live(url)["tournament"]["status"]))

        aborted = json.loads(json.dumps(playoff))
        aborted.update(status="aborted", completion_reason="operator_requested")
        _write_scenario_projection(scenario_directory, aborted)
        observed.append(str(_read_live(url)["tournament"]["status"]))
    finally:
        _stop_process(process)
    return {
        "phase_transition_observed": (
            qualifying_phase == "qualifying" and playoff_phase == "playoff"
        ),
        "states_observed": observed,
        "pending_review_observed": "awaiting_security_ruling" in observed,
        "abort_observed": "aborted" in observed,
    }


def _rehearse_presentation(directory: Path) -> Mapping[str, Any]:
    """Read live and replay data across an independent process restart."""

    before = _competitive_snapshot(directory)
    projection = load_scoreboard_projection(directory)
    if projection is None:
        raise RuntimeError("presentation rehearsal requires a Scoreboard Projection")
    match_ids = [
        str(match["match_id"])
        for fixture in projection.get("fixtures", [])
        for match in fixture.get("matches", [])
    ]
    bracket = projection.get("bracket")
    if isinstance(bracket, dict):
        match_ids.extend(
            str(match["match_id"])
            for fixture in bracket.get("fixtures", [])
            for match in fixture.get("matches", [])
        )
    if not match_ids:
        raise RuntimeError("presentation rehearsal requires a completed Match")

    live_process, live_url = _start_presentation_process(directory)
    try:
        _read_live(live_url)
    finally:
        _stop_process(live_process)

    replay_process, replay_base_url = _start_presentation_process(directory)
    try:
        replay_url = (
            replay_base_url
            + "api/matches/"
            + quote(match_ids[0], safe="")
            + "/replay"
        )
        with urlopen(replay_url, timeout=10) as response:
            if response.status != 200:
                raise RuntimeError("presentation replay read failed")
            response.read()
    finally:
        _stop_process(replay_process)

    lifecycle = _rehearse_presentation_lifecycle(
        directory, projection, match_ids[0]
    )
    if not all(
        lifecycle.get(field) is True
        for field in (
            "phase_transition_observed",
            "pending_review_observed",
            "abort_observed",
        )
    ):
        raise RuntimeError("presentation lifecycle rehearsal was incomplete")

    after = _competitive_snapshot(directory)
    checks = {
        "competition_record_bytes_unchanged": (
            before["record_bytes"] == after["record_bytes"]
        ),
        "scoreboard_projection_unchanged": (
            before["projection_bytes"] == after["projection_bytes"]
        ),
        "reconstructed_state_unchanged": before["state"] == after["state"],
        "tournament_champion_unchanged": (
            before["champion"] == after["champion"]
        ),
    }
    if not all(checks.values()):
        raise RuntimeError("presentation reads changed authoritative Tournament data")
    return {
        "separate_process": True,
        "interrupted": True,
        "resumed": True,
        "live_read_verified": True,
        "replay_read_verified": True,
        "lifecycle": lifecycle,
        **checks,
    }


def _sysctl(name: str) -> str:
    try:
        completed = subprocess.run(
            ["sysctl", "-n", name],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("target machine inspection failed: " + str(error))
    if completed.returncode != 0 or not completed.stdout.strip():
        raise RuntimeError("target machine did not report " + name)
    return completed.stdout.strip()


def _inspect_target_machine() -> Mapping[str, Any]:
    return {
        "system": platform.system(),
        "architecture": platform.machine(),
        "logical_cpus": os.cpu_count(),
        "model": _sysctl("hw.model"),
        "processor": _sysctl("machdep.cpu.brand_string"),
        "memory_bytes": int(_sysctl("hw.memsize")),
    }


def _approve_plan(evidence: Mapping[str, Any], output: TextIO) -> bool:
    print("Validated Tournament plan review:", file=output)
    print(json.dumps(evidence, indent=2, sort_keys=True), file=output)
    try:
        response = input(
            "Review the preserved tournament-plan.json, then type APPROVE to seal it: "
        )
    except EOFError:
        return False
    return response == "APPROVE"


def _read_json(path: Path, description: str) -> Mapping[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(description + " is missing or is not a regular file")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(description + " is corrupt: " + str(error)) from error
    if not isinstance(value, dict):
        raise ValueError(description + " must be a JSON object")
    return value


def _team_count(path: Path) -> int:
    mapping = _read_json(path, "Team source mapping")
    teams = mapping.get("teams")
    if not isinstance(teams, list) or len(teams) != TEAM_COUNT:
        raise ValueError(
            "full rehearsal requires exactly sixteen Team source directories"
        )
    for ordinal, team in enumerate(teams):
        if not isinstance(team, dict):
            raise ValueError("Team source mapping entry must be an object")
        source = team.get("source_directory")
        if not isinstance(source, str) or not Path(source).expanduser().is_dir():
            raise ValueError(
                "Team source mapping entry "
                + str(ordinal)
                + " does not name a valid local source directory"
            )
    return len(teams)


def _review_plan(plan_path: Path, store: Path, catalog_path: Path) -> Mapping[str, Any]:
    catalog = load_catalog(catalog_path)
    validated = validate_tournament_plan(plan_path, store, catalog)
    if len(validated.roster) != TEAM_COUNT:
        raise ValueError("rehearsal plan does not contain exactly sixteen Teams")
    if validated.config.execution_mode != "continuous":
        raise ValueError("rehearsal plan is not in Continuous Mode")
    if validated.config.continuous_parallelism != MATCH_PARALLELISM:
        raise ValueError("rehearsal plan does not use four concurrent Matches")
    plan = _read_json(plan_path, "Tournament plan")
    teams = plan.get("teams")
    assert isinstance(teams, list)
    manifests = [team["bot_artifact_manifest"] for team in teams]
    return {
        "team_count": len(validated.roster),
        "tournament_seed": validated.tournament_seed,
        "execution_mode": validated.config.execution_mode,
        "parallelism": validated.config.continuous_parallelism,
        "execution_profile": plan["execution_profile"],
        "resource_values": plan["global_resources"],
        "artifact_identities": [manifest["artifact_digest"] for manifest in manifests],
        "runtime_identities": sorted(
            {str(manifest["runtime_digest"]) for manifest in manifests}
        ),
        "validation_identities": [
            manifest["validation_identity"] for manifest in manifests
        ],
        "teams": [
            {
                "team_id": team["team_id"],
                "display_name": team["display_name"],
                "source_identity": team["selected_source"]["source_digest"],
                "artifact_identity": team["bot_artifact_manifest"][
                    "artifact_digest"
                ],
            }
            for team in teams
        ],
    }


def _doctor_image_requirements(
    plan_path: Path, batch: Path
) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    plan = _read_json(plan_path, "Tournament plan")
    teams = plan.get("teams")
    if not isinstance(teams, list) or not teams:
        raise ValueError("Tournament plan has no selected Bot Artifacts")
    organizer_images: set[str] = set()
    for team in teams:
        if not isinstance(team, dict):
            raise ValueError("Tournament plan Team is invalid")
        manifest = team.get("bot_artifact_manifest")
        if not isinstance(manifest, dict):
            raise ValueError("Tournament plan Bot Artifact Manifest is invalid")
        retention = manifest.get("retention")
        if not isinstance(retention, dict):
            raise ValueError("Bot Artifact Manifest has no retention evidence")
        organizer_images.add(str(retention["local_image_id"]))
    first_team = teams[0]
    assert isinstance(first_team, dict)
    team_id = str(first_team["team_id"])
    validation = _read_json(
        batch / "teams" / team_id / "certification" / "validation-report.json",
        "retained validation report",
    )
    smoke = validation.get("smoke_match")
    practices = smoke.get("practice_artifacts") if isinstance(smoke, dict) else None
    if not isinstance(practices, dict):
        raise ValueError("validation report has no retained practice Bot Artifacts")
    practice_images = []
    for name, evidence in sorted(practices.items()):
        if not isinstance(evidence, dict) or not isinstance(
            evidence.get("cached_image_id"), str
        ):
            raise ValueError("practice Bot Artifact has no retained image identity")
        practice_images.append((str(name), str(evidence["cached_image_id"])))
    return tuple(sorted(organizer_images)), tuple(practice_images)


def _docker_remove(reference: str) -> None:
    try:
        completed = subprocess.run(
            ["docker", "image", "rm", reference],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("could not remove rehearsal-owned image: " + str(error))
    if completed.returncode != 0:
        diagnostic = (completed.stderr or completed.stdout).strip()
        if "no such image" not in diagnostic.lower():
            raise RuntimeError(
                "could not remove rehearsal-owned image "
                + repr(reference)
                + (": " + diagnostic if diagnostic else "")
            )


def _prove_archive_restore(plan_path: Path, store: Path) -> Mapping[str, Any]:
    plan = _read_json(plan_path, "Tournament plan")
    teams = plan.get("teams")
    if not isinstance(teams, list):
        raise ValueError("Tournament plan teams are missing")
    artifacts: dict[tuple[str, str], Mapping[str, Any]] = {}
    references: set[str] = set()
    for team in teams:
        if not isinstance(team, dict) or not isinstance(
            team.get("bot_artifact_manifest"), dict
        ):
            raise ValueError("Tournament plan Bot Artifact Manifest is invalid")
        manifest = team["bot_artifact_manifest"]
        digest = str(manifest["artifact_digest"])
        platform = str(manifest["platform"])
        artifacts[(digest, platform)] = manifest
        retention = manifest.get("retention")
        if not isinstance(retention, dict):
            raise ValueError("Bot Artifact Manifest has no retention record")
        references.add(str(retention["local_image_reference"]))
    for reference in sorted(references):
        _docker_remove(reference)
    archive_loads = 0
    for digest, platform in sorted(artifacts):
        telemetry: dict[str, object] = {}
        resolve_artifact(store, digest, platform, operational_telemetry=telemetry)
        if telemetry.get("status") != "verified":
            raise RuntimeError(
                "selected Bot Artifact did not resolve exactly: " + digest
            )
        if telemetry.get("archive_restored") is True:
            archive_loads += 1
    if archive_loads == 0:
        raise RuntimeError("selected Bot Artifact archive was not used for restoration")
    return {
        "status": "passed",
        "selected_images": len(artifacts),
        "restored_images": len(artifacts),
        "archive_loads": archive_loads,
    }


def _competition_state_identity(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in (
        directory / "manifest.json",
        *(sorted((directory / "records").glob("*.json"))),
    ):
        digest.update(path.name.encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
    return "sha256:" + digest.hexdigest()


def _contains_timing_objective(value: Any) -> bool:
    forbidden = {
        "elapsed_seconds",
        "objective_seconds",
        "objective_result",
        "phase_timings_seconds",
        "total_elapsed_seconds",
    }
    if isinstance(value, dict):
        return bool(forbidden & set(value)) or any(
            _contains_timing_objective(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_timing_objective(item) for item in value)
    return False


def _verify_tournament(directory: Path) -> Mapping[str, Any]:
    stored_manifest = load_manifest(directory)
    manifest = stored_manifest.manifest
    records = load_competition_records(directory)
    state = fold_tournament_state(manifest, records)
    projection = load_scoreboard_projection(directory)
    telemetry = load_operational_telemetry(directory)
    terminals = [
        item.record
        for item in records
        if item.record.get("type") == "match_terminal"
    ]
    by_fixture = Counter(str(record.get("fixture_id")) for record in terminals)
    if manifest.get("scheduled_turns_per_match") != SCHEDULED_TURNS_PER_MATCH:
        raise RuntimeError("Tournament did not seal 300 scheduled Turns per Match")
    if len(by_fixture) != EXPECTED_FIXTURES or set(by_fixture.values()) != {3}:
        raise RuntimeError("Tournament did not exercise three Matches in every Series")
    if len(terminals) != EXPECTED_MATCHES:
        raise RuntimeError("Tournament did not complete the expected 369 Matches")
    if any(
        len(record.get("rounds", [])) != SCHEDULED_TURNS_PER_MATCH
        for record in terminals
    ):
        raise RuntimeError("a rehearsal Match did not complete all 300 scheduled Turns")
    if any(
        any(value is not None for value in record.get("faults", {}).values())
        for record in terminals
    ):
        raise RuntimeError("a rehearsal Bot Artifact produced a competitive fault")
    if any(item.get("infrastructure_failure") is True for item in telemetry):
        raise RuntimeError(
            "rehearsal Operational Telemetry contains an Infrastructure Failure"
        )
    if not telemetry:
        raise RuntimeError("rehearsal produced no Operational Telemetry")
    if not state.is_complete or state.was_aborted:
        raise RuntimeError("rehearsal Tournament did not reach canonical completion")
    if projection is None or projection.get("status") != "complete":
        raise RuntimeError("Scoreboard Projection does not show Tournament completion")
    if projection.get("champion") != state.champion_team_id:
        raise RuntimeError(
            "Scoreboard Projection Champion disagrees with reconstructed state"
        )
    if any(_contains_timing_objective(item.record) for item in records) or (
        _contains_timing_objective(projection)
    ):
        raise RuntimeError(
            "timing objective leaked into Competition Records or Scoreboard Projection"
        )
    return {
        "status": "complete",
        "scheduled_turns_per_match": SCHEDULED_TURNS_PER_MATCH,
        "fixture_count": len(by_fixture),
        "match_count": len(terminals),
        "all_series_used_three_matches": True,
        "competition_records_verified": True,
        "operational_telemetry_verified": True,
        "scoreboard_projection_verified": True,
        "state_reconstruction_verified": True,
        "timing_isolation_verified": True,
        "tournament_champion": state.champion_team_id,
        "canonical_no_champion": state.ended_without_champion,
        "competition_state_identity": _competition_state_identity(directory),
    }


DEFAULT_OPERATIONS = RehearsalOperations(
    inspect_configuration=diagnose_host_readiness,
    inspect_target_machine=_inspect_target_machine,
    run_batch=_run_batch,
    review_plan=_review_plan,
    approve_plan=_approve_plan,
    prove_archive_restore=_prove_archive_restore,
    run_tournament=_run_tournament,
    rehearse_presentation=_rehearse_presentation,
    verify_tournament=_verify_tournament,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rps-rehearse",
        description="Run the explicit sixteen-Team release-readiness rehearsal",
    )
    parser.add_argument("--teams", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--tournament-seed", required=True, type=int)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--parallelism", required=True, type=int)
    parser.add_argument("--jobs", required=True, type=int)
    parser.add_argument("--expected-context")
    return parser


def _write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")


def _timed(
    name: str,
    function: Callable[[], Any],
    timings: dict[str, float],
    clock: Callable[[], float],
) -> Any:
    started = clock()
    result = function()
    timings[name] = round(clock() - started, 6)
    return result


def _validate_target_machine(machine: Mapping[str, Any]) -> None:
    if machine.get("system") != "Darwin" or machine.get("architecture") != "arm64":
        raise RuntimeError("rehearsal target must be an Apple Silicon Mac")
    if machine.get("logical_cpus") != 16:
        raise RuntimeError(
            "rehearsal target must expose exactly sixteen logical CPUs"
        )
    if "M4 Max" not in str(machine.get("processor")):
        raise RuntimeError("rehearsal target processor must be an Apple M4 Max")
    if machine.get("memory_bytes") != 128 * 1024**3:
        raise RuntimeError("rehearsal target must have exactly 128 GiB memory")


def main(
    arguments: Optional[list[str]] = None,
    *,
    operations: RehearsalOperations = DEFAULT_OPERATIONS,
    clock: Callable[[], float] = time.monotonic,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    output_stream = stdout or sys.stdout
    error_stream = stderr or sys.stderr
    options = build_parser().parse_args(arguments)
    output = options.output.expanduser().resolve()
    report_path = output / "rehearsal-report.json"
    base_report: dict[str, Any] = {
        "rehearsal_report_format_version": REHEARSAL_REPORT_FORMAT_VERSION,
        "status": "failed",
        "objective_seconds": OBJECTIVE_SECONDS,
        "objective_result": "not_evaluated",
        "platform": "linux/arm64",
        "parallelism": options.parallelism,
        "build_jobs": options.jobs,
        "tournament_seed": options.tournament_seed,
        "source_mapping": str(options.teams.expanduser().resolve()),
        "environment": options.environment,
        "team_count": None,
        "phase_timings_seconds": {},
    }
    try:
        setup_started = clock()
        automated_started = setup_started
        if output.exists() or output.is_symlink():
            raise ValueError(
                "output destination already exists and will not be replaced"
            )
        output.mkdir(parents=True)
        base_report["team_count"] = _team_count(options.teams.expanduser().resolve())
        if options.profile != CONTAINER_ISOLATION_PROFILE_VERSION:
            raise ValueError("rehearsal requires the published execution profile")
        if options.parallelism != MATCH_PARALLELISM:
            raise ValueError("rehearsal requires exactly four concurrent Matches")
        if options.jobs <= 0:
            raise ValueError("build jobs must be a positive integer")
        if not 0 <= options.tournament_seed < 1 << 64:
            raise ValueError("Tournament Seed must be an unsigned 64-bit integer")

        catalog_path = options.catalog.expanduser().resolve()
        catalog = load_catalog(catalog_path)
        batch = output / "batch"
        store = batch / "artifact-store"
        plan = batch / "tournament-plan.json"
        tournament = output / "tournament"
        timings: dict[str, float] = {
            "input_validation": round(clock() - setup_started, 6)
        }
        base_report["phase_timings_seconds"] = timings
        batch_code = _timed(
            "build_validation_preservation",
            lambda: operations.run_batch(
                [
                    "--teams", str(options.teams.expanduser().resolve()),
                    "--catalog", str(catalog_path),
                    "--environment", options.environment,
                    "--output", str(batch),
                    "--tournament-seed", str(options.tournament_seed),
                    "--execution-mode", "continuous",
                    "--parallelism", str(MATCH_PARALLELISM),
                    "--jobs", str(options.jobs),
                    "--retain-practice-images",
                ]
            ),
            timings,
            clock,
        )
        if batch_code != 0:
            raise RuntimeError("public batch-plan command failed")
        organizer_images, practice_artifacts = _doctor_image_requirements(
            plan, batch
        )
        configuration_request = HostReadinessRequest(
            catalog=catalog_path,
            platform="linux/arm64",
            artifact_store=store,
            parallelism=MATCH_PARALLELISM,
            expected_context=options.expected_context,
            organizer_images=organizer_images,
            practice_artifacts=practice_artifacts,
        )
        configuration = _timed(
            "configuration",
            lambda: {
                "readiness": operations.inspect_configuration(
                    configuration_request
                ),
                "target_machine": operations.inspect_target_machine(),
            },
            timings,
            clock,
        )
        readiness = configuration["readiness"]
        target_machine = configuration["target_machine"]
        if readiness.get("ready") is not True:
            raise RuntimeError("prepared organizer configuration is not ready")
        _validate_target_machine(target_machine)
        plan_evidence = _timed(
            "plan_review",
            lambda: operations.review_plan(plan, store, catalog_path),
            timings,
            clock,
        )
        approval_started = clock()
        if not operations.approve_plan(plan_evidence, output_stream):
            raise RuntimeError(
                "validated Tournament plan was not approved for sealing"
            )
        approval_seconds = round(clock() - approval_started, 6)
        archive = _timed(
            "archive_restore",
            lambda: operations.prove_archive_restore(plan, store),
            timings,
            clock,
        )
        runner_rehearsal = _timed(
            "tournament_execution",
            lambda: operations.run_tournament(
                [
                    "plan", "--plan", str(plan), "--catalog", str(catalog_path),
                    "--artifact-store", str(store), "--directory", str(tournament),
                    "--tournament-id", "sixteen-team-release-rehearsal", "--continuous",
                ]
            ),
            timings,
            clock,
        )
        if runner_rehearsal.get("exit_code") != 0:
            raise RuntimeError("public Tournament command failed")
        if not all(
            runner_rehearsal.get(field) is True
            for field in ("separate_process", "interrupted", "resumed")
        ):
            raise RuntimeError("public Runner interruption rehearsal was incomplete")
        active_presentation = runner_rehearsal.get(
            "presentation_while_runner_active"
        )
        if not isinstance(active_presentation, dict) or not all(
            active_presentation.get(field) is True
            for field in (
                "separate_process",
                "interrupted",
                "resumed",
                "runner_remained_active",
            )
        ):
            raise RuntimeError(
                "presentation independence from the active Runner was not proven"
            )
        presentation_rehearsal = _timed(
            "presentation_rehearsal",
            lambda: operations.rehearse_presentation(tournament),
            timings,
            clock,
        )
        lifecycle = presentation_rehearsal.get("lifecycle")
        if not isinstance(lifecycle, dict) or not all(
            lifecycle.get(field) is True
            for field in (
                "phase_transition_observed",
                "pending_review_observed",
                "abort_observed",
            )
        ):
            raise RuntimeError("presentation lifecycle rehearsal was incomplete")
        tournament_evidence = _timed(
            "public_verification",
            lambda: operations.verify_tournament(tournament),
            timings,
            clock,
        )
        elapsed = round(clock() - automated_started - approval_seconds, 6)
        objective_met = elapsed <= OBJECTIVE_SECONDS
        machine = readiness["machine"]
        docker = readiness["docker"]
        base_report.update(
            {
                "status": "passed" if objective_met else "failed",
                "objective_result": "met" if objective_met else "exceeded",
                "total_elapsed_seconds": elapsed,
                "machine_identity": machine["identity"],
                "machine": machine,
                "target_machine": target_machine,
                "engine_identity": docker["engine_identity"],
                "docker_context": docker["context"],
                "docker_version": docker.get("server_version"),
                "engine": docker,
                "catalog_identity": catalog.identity,
                "catalog": {"version": catalog.version, "identity": catalog.identity},
                "profile_identity": INITIAL_EXECUTION_PROFILE.identity,
                "profile": {
                    "version": options.profile,
                    "identity": INITIAL_EXECUTION_PROFILE.identity,
                },
                "resource_values": dict(INITIAL_EXECUTION_PROFILE.as_mapping()),
                "phase_timings_seconds": timings,
                "artifacts": dict(plan_evidence),
                "plan_review": {"status": "approved"},
                "plan_approval_seconds_excluded": approval_seconds,
                "archive_restore": dict(archive),
                "event_day": {
                    "runner": dict(runner_rehearsal),
                    "presentation": dict(presentation_rehearsal),
                },
                "tournament": dict(tournament_evidence),
                "capacity_contract": {"maximum_teams": 32},
            }
        )
        if not objective_met:
            base_report["failure_kind"] = "timing_objective"
            base_report["failure_detail"] = "automated rehearsal exceeded forty minutes"
        _write_report(report_path, base_report)
        print(json.dumps(base_report, indent=2, sort_keys=True), file=output_stream)
        return 0 if objective_met else TIMING_OBJECTIVE_EXIT_CODE
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
        base_report["failure_kind"] = "correctness"
        base_report["failure_detail"] = str(error)
        if output.is_dir() and not report_path.exists():
            _write_report(report_path, base_report)
        print("rps-rehearse: " + str(error), file=error_stream)
        return CORRECTNESS_FAILURE_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
