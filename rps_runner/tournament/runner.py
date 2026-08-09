"""Highest-level Tournament creation, controls, and execution orchestration."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Optional, Union

from rps_runner.engine import CONTAINER_ISOLATION_PROFILE_VERSION
from rps_runner.execution_profile import INITIAL_EXECUTION_PROFILE

from .competition import (
    MatchOutcome,
    MatchResult,
    Phase,
    Series,
    Standing,
)
from .locking import TournamentRunLock
from .match_executor import MatchExecutionRequest, MatchExecutionResult
from .rules import manifest_rules
from .schedule import (
    Fixture,
    FixtureBatch,
    bot_positions,
    build_qualifying_schedule,
)
from .seeding import (
    SEED_DERIVATION_VERSION,
    derive_bot_seed,
    derive_match_seed,
    derive_tiebreak_key,
)
from .state import (
    NO_ELIGIBLE_FINALIST_REASON,
    NO_ELIGIBLE_TEAMS_REASON,
    OPERATOR_ABORT_REASON,
    TournamentState,
    build_operator_abort_record,
    build_playoff_bracket_record,
    build_sole_eligible_champion_record,
    build_tournament_ended_without_champion_record,
    build_security_violation_ruling_record,
    build_security_violation_suspected_record,
    build_tournament_champion_record,
    fold_tournament_state,
)
from .storage import (
    StoredCompetitionRecord,
    _restore_competition_record_under_run_lock,
    append_competition_record,
    append_competition_record_to_verified_sequence,
    append_operational_telemetry,
    initial_control_state,
    load_competition_records,
    load_control_state,
    load_manifest,
    load_operational_telemetry,
    load_scoreboard_projection,
    seal_manifest,
    update_control_state,
    write_control_state,
    write_scoreboard_projection,
)


PROTOCOL_VERSION = 1
RECORD_SCHEMA_VERSION = 5
SCOREBOARD_VERSION = 1
SCHEDULED_TURNS_PER_MATCH = 300
FIRST_MOVE_TIMEOUT_MS = INITIAL_EXECUTION_PROFILE.first_move_timeout_ms
MOVE_TIMEOUT_MS = INITIAL_EXECUTION_PROFILE.move_timeout_ms
TOTAL_TIMEOUT_MS = INITIAL_EXECUTION_PROFILE.total_timeout_ms
STDERR_LIMIT_BYTES = INITIAL_EXECUTION_PROFILE.stderr_limit_bytes
_MAX_U64 = (1 << 64) - 1
_TEAM_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,62}\Z")
_LANGUAGE_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")
_DIGEST_PATTERN = re.compile(r"[0-9a-fA-F]{64}\Z")


@dataclass(frozen=True)
class MatchLimits:
    first_move_timeout_ms: int = FIRST_MOVE_TIMEOUT_MS
    move_timeout_ms: int = MOVE_TIMEOUT_MS
    total_timeout_ms: int = TOTAL_TIMEOUT_MS
    stderr_limit_bytes: int = STDERR_LIMIT_BYTES
    stdout_limit_bytes: int = INITIAL_EXECUTION_PROFILE.stdout_limit_bytes
    cpu_limit_ms: int = INITIAL_EXECUTION_PROFILE.cpu_limit_ms
    cpu_quota_millis_per_second: int = (
        INITIAL_EXECUTION_PROFILE.cpu_quota_millis_per_second
    )
    memory_limit_bytes: int = INITIAL_EXECUTION_PROFILE.memory_limit_bytes
    process_limit: int = INITIAL_EXECUTION_PROFILE.process_limit
    open_file_limit: int = INITIAL_EXECUTION_PROFILE.open_file_limit
    filesystem_write_limit_bytes: int = (
        INITIAL_EXECUTION_PROFILE.filesystem_write_limit_bytes
    )
    network_access_allowed: bool = False


@dataclass(frozen=True)
class TournamentConfig:
    execution_mode: str = "step"
    match_limits: MatchLimits = MatchLimits()
    continuous_parallelism: int = 1
    execution_profile_version: str = CONTAINER_ISOLATION_PROFILE_VERSION


@dataclass(frozen=True)
class BotArtifactManifest:
    artifact_digest: str
    language_id: str
    wrapper_version: str
    runtime_digest: str
    entrypoint: tuple[str, ...]


class InfrastructureInterventionRequiredError(RuntimeError):
    """Three Match Attempts failed and operator intervention is required."""

    def __init__(self, match_id: str, attempt_count: int):
        self.match_id = match_id
        self.attempt_count = attempt_count
        super().__init__(
            f"{match_id} failed {attempt_count} Match Attempts; "
            "infrastructure intervention is required"
        )


class TournamentCompatibilityError(RuntimeError):
    """The sealed Tournament uses an unsupported compatibility value."""

    def __init__(self, field: str, expected: object, actual: object):
        self.field = field
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Unsupported {field}: expected {expected!r}, found {actual!r}"
        )


class ArtifactDigestVerificationError(RuntimeError):
    """A sealed Bot Artifact no longer matches its canonical digest."""

    def __init__(self, team_id: str, artifact_digest: str):
        self.team_id = team_id
        self.artifact_digest = artifact_digest
        super().__init__(f"Bot Artifact digest verification failed for {team_id}")


class SecurityRulingRequiredError(RuntimeError):
    """Tournament execution is paused for an organizer ruling."""

    def __init__(self, match_id: str):
        self.match_id = match_id
        super().__init__(
            f"{match_id} has a suspected Security Violation awaiting a ruling"
        )


@dataclass(frozen=True)
class Team:
    team_id: str
    display_name: str
    bot_artifact: BotArtifactManifest


@dataclass(frozen=True)
class _ScheduledMatchAttempt:
    fixture: dict[str, Any]
    match_ordinal: int
    request: MatchExecutionRequest


@dataclass(frozen=True)
class _CompletedMatchAttempt:
    scheduled: _ScheduledMatchAttempt
    result: Optional[MatchExecutionResult] = None
    error: Optional[BaseException] = None


@dataclass
class TournamentRunner:
    tournament_directory: Path
    match_executor: Callable[[MatchExecutionRequest], MatchExecutionResult]
    _manifest: dict[str, Any]

    @classmethod
    def create(
        cls,
        tournament_directory: Union[Path, str],
        *,
        tournament_id: str,
        tournament_seed: int,
        roster: Iterable[Team],
        config: TournamentConfig = TournamentConfig(),
        match_executor: Callable[[MatchExecutionRequest], MatchExecutionResult],
    ) -> "TournamentRunner":
        manifest = _build_manifest_payload(
            tournament_id=tournament_id,
            tournament_seed=tournament_seed,
            roster=roster,
            config=config,
        )
        directory = Path(tournament_directory)
        directory.mkdir(parents=True, exist_ok=True)
        with TournamentRunLock(directory):
            stored = seal_manifest(directory, manifest)
            write_control_state(
                directory, initial_control_state(config.execution_mode)
            )
            write_scoreboard_projection(
                directory,
                _initial_projection(stored.manifest),
            )
        return cls(directory, match_executor, stored.manifest)

    @classmethod
    def open(
        cls,
        tournament_directory: Union[Path, str],
        *,
        match_executor: Callable[[MatchExecutionRequest], MatchExecutionResult],
        artifact_digest_verifier: Callable[[str, str], bool],
        sealed_manifest_verifier: Optional[
            Callable[[dict[str, Any]], None]
        ] = None,
    ) -> "TournamentRunner":
        directory = Path(tournament_directory)
        with TournamentRunLock(directory):
            stored = load_manifest(directory)
            _verify_compatibility(stored.manifest)
            _verify_artifact_digests(
                stored.manifest, artifact_digest_verifier
            )
            if sealed_manifest_verifier is not None:
                sealed_manifest_verifier(stored.manifest)
            records = load_competition_records(directory)
            control = load_control_state(directory)
            if control is None:
                control = write_control_state(
                    directory,
                    initial_control_state(str(stored.manifest["execution_mode"])),
                )
            elif control["lifecycle"] == "running":
                control = update_control_state(
                    directory,
                    lambda value: {
                        **value,
                        "lifecycle": "paused",
                        "match_active": False,
                    },
                )
            load_operational_telemetry(directory)
            state = fold_tournament_state(stored.manifest, records)
            records, state = _commit_canonical_transitions_if_ready(
                directory, stored.manifest, records, state
            )
            write_scoreboard_projection(
                directory,
                _projection_from_records(stored.manifest, records, state),
            )
        return cls(directory, match_executor, stored.manifest)

    @classmethod
    def restore_competition_record_at(
        cls,
        tournament_directory: Union[Path, str],
        backup_record_path: Union[Path, str],
    ) -> StoredCompetitionRecord:
        """Restore one indexed Competition Record before opening a Tournament."""

        directory = Path(tournament_directory)
        with TournamentRunLock(directory):
            stored = load_manifest(directory)
            _verify_compatibility(stored.manifest)
            return _restore_competition_record_under_run_lock(
                directory, backup_record_path
            )

    @property
    def status(self) -> str:
        projection = load_scoreboard_projection(self.tournament_directory)
        if projection is None:
            return "paused"
        return str(projection["status"])

    @property
    def current_mode(self) -> str:
        """Return the durable operational execution mode."""

        control = self._control_state()
        return str(control["current_mode"])

    @property
    def control_status(self) -> str:
        """Return operational lifecycle distinct from competition status."""

        return str(self._control_state()["lifecycle"])

    def start(self) -> tuple[StoredCompetitionRecord, ...]:
        """Explicitly start a paused Continuous Mode Tournament."""

        return self._run_continuously(
            allow_infrastructure_intervention=False
        )

    def resume(self) -> tuple[StoredCompetitionRecord, ...]:
        """Resume a paused Continuous Mode Tournament at its canonical boundary."""

        return self._run_continuously(
            allow_infrastructure_intervention=True
        )

    def request_pause(self) -> None:
        """Durably request a pause after the active Match reaches its boundary."""

        self.request_pause_at(self.tournament_directory)

    @classmethod
    def request_pause_at(
        cls, tournament_directory: Union[Path, str]
    ) -> None:
        """Request pause without competing for an active Tournament run lock."""

        directory = Path(tournament_directory)
        manifest = load_manifest(directory).manifest
        _verify_compatibility(manifest)
        if load_control_state(directory) is None:
            raise RuntimeError("Tournament control state is missing")

        def request(control: dict[str, Any]) -> dict[str, Any]:
            if control["lifecycle"] == "running":
                control["pause_requested"] = True
            return control

        update_control_state(directory, request)

    def switch_mode(self, execution_mode: str) -> None:
        """Switch Step/Continuous Mode only while paused at a Match boundary."""

        if execution_mode not in ("step", "continuous"):
            raise ValueError("Execution mode must be step or continuous")
        control = self._control_state()
        if control["lifecycle"] != "paused":
            raise ValueError("Execution mode can change only at a Match boundary")
        with TournamentRunLock(self.tournament_directory):
            records = load_competition_records(self.tournament_directory)
            state = fold_tournament_state(self._manifest, records)
            if state.is_complete:
                raise ValueError("A complete Tournament has no execution mode")
            if state.pending_security_ruling is not None:
                raise ValueError(
                    "Execution mode cannot change while a Security Violation "
                    "ruling is pending"
                )
            control = self._control_state()
            if control["lifecycle"] != "paused":
                raise ValueError("Execution mode can change only at a Match boundary")
            update_control_state(
                self.tournament_directory,
                lambda value: {
                    **value,
                    "current_mode": execution_mode,
                    "pause_requested": False,
                },
            )

    def run_continuously(self) -> tuple[StoredCompetitionRecord, ...]:
        """Advance a Continuous Mode Tournament to its next stop boundary."""

        return self._run_continuously(
            allow_infrastructure_intervention=True
        )

    def _run_continuously(
        self, *, allow_infrastructure_intervention: bool
    ) -> tuple[StoredCompetitionRecord, ...]:
        if self.current_mode != "continuous":
            raise ValueError(
                "Continuous execution requires execution_mode continuous: "
                "a Tournament sealed in Continuous Mode or switched to "
                "current Continuous Mode"
            )
        if self._state().is_complete:
            return ()
        self._begin_execution(
            expected_mode="continuous",
            allow_intervention=allow_infrastructure_intervention,
        )
        committed: list[StoredCompetitionRecord] = []
        try:
            parallelism = int(self._manifest.get("continuous_parallelism", 1))
            if parallelism > 1:
                with TournamentRunLock(self.tournament_directory):
                    committed.extend(self._run_parallel_matches(parallelism))
                self._set_lifecycle("paused", clear_pause=True)
                return tuple(committed)
            with TournamentRunLock(self.tournament_directory):
                while True:
                    record = self._play_next_match(run_lock_already_held=True)
                    if record is None:
                        self._set_lifecycle("paused")
                        return tuple(committed)
                    if record.record["type"] == "security_violation_suspected":
                        self._set_lifecycle("paused")
                        return tuple(committed)
                    committed.append(record)
                    if self._pause_is_requested():
                        self._set_lifecycle("paused", clear_pause=True)
                        return tuple(committed)
        except InfrastructureInterventionRequiredError:
            self._set_lifecycle("infrastructure_intervention")
            raise
        except BaseException:
            self._set_lifecycle("paused")
            raise

    def _run_parallel_matches(
        self, parallelism: int
    ) -> tuple[StoredCompetitionRecord, ...]:
        """Run independent Matches while publishing only the canonical prefix."""

        records = load_competition_records(self.tournament_directory)
        state = fold_tournament_state(self._manifest, records)
        committed: list[StoredCompetitionRecord] = []
        buffered: dict[str, _CompletedMatchAttempt] = {}
        active: dict[Future[MatchExecutionResult], _ScheduledMatchAttempt] = {}
        halt_scheduling = False
        retrying_match_ids: set[str] = set()
        deferred_error: Optional[BaseException] = None

        with ThreadPoolExecutor(max_workers=parallelism) as executor:
            while True:
                records, state, prefix_error = self._commit_parallel_prefix(
                    records, state, buffered, committed
                )
                if prefix_error is not None:
                    halt_scheduling = True
                    deferred_error = prefix_error
                    if not active:
                        if deferred_error is not None:
                            raise deferred_error
                        return tuple(committed)

                if state.is_complete and not active:
                    return tuple(committed)

                if self._pause_is_requested():
                    halt_scheduling = True

                if not halt_scheduling and not retrying_match_ids:
                    candidates = _runnable_matches(self._manifest, state)
                    if (
                        state.phase is Phase.PLAYOFF
                        and candidates
                        and not state.bracket_locked
                    ):
                        fixture, match_ordinal = candidates[0]
                        match_id = (
                            f"{fixture['fixture_id']}-match-{match_ordinal}"
                        )
                        bracket_lock_record = append_competition_record(
                            self.tournament_directory,
                            {
                                "type": "playoff_bracket_locked",
                                "phase": Phase.PLAYOFF.value,
                                "fixture_id": fixture["fixture_id"],
                                "match_id": match_id,
                            },
                        )
                        records = records + [bracket_lock_record]
                        state = fold_tournament_state(self._manifest, records)
                        candidates = _runnable_matches(self._manifest, state)

                    active_ids = {
                        scheduled.request.match_id for scheduled in active.values()
                    }
                    active_team_ids = {
                        team_id
                        for scheduled in active.values()
                        for team_id in (
                            scheduled.request.team_a_id,
                            scheduled.request.team_b_id,
                        )
                    }
                    for fixture, match_ordinal in candidates:
                        if len(active) >= parallelism:
                            break
                        match_id = (
                            f"{fixture['fixture_id']}-match-{match_ordinal}"
                        )
                        if match_id in active_ids or match_id in buffered:
                            continue
                        fixture_team_ids = set(fixture["team_ids"])
                        if not active_team_ids.isdisjoint(fixture_team_ids):
                            continue
                        request = _build_match_request(
                            self._manifest,
                            fixture,
                            match_ordinal,
                            attempt_number=_next_attempt_number(
                                self.tournament_directory, match_id
                            ),
                        )
                        scheduled = _ScheduledMatchAttempt(
                            fixture, match_ordinal, request
                        )
                        if not self._claim_parallel_match_boundary():
                            halt_scheduling = True
                            break
                        self._project_active_matches(
                            records, tuple(active.values()) + (scheduled,)
                        )
                        self._record_match_attempt_start(request)
                        active[executor.submit(self.match_executor, request)] = (
                            scheduled
                        )
                        active_ids.add(match_id)
                        active_team_ids.update(fixture_team_ids)
                    self._project_active_matches(records, active.values())

                if not active:
                    if halt_scheduling:
                        if deferred_error is not None:
                            raise deferred_error
                        return tuple(committed)
                    if state.is_complete or not _runnable_matches(
                        self._manifest, state
                    ):
                        return tuple(committed)
                    raise AssertionError("Runnable Matches could not be scheduled")

                done, _pending = wait(active, return_when=FIRST_COMPLETED)
                for future in done:
                    scheduled = active.pop(future)
                    retrying_match_ids.discard(scheduled.request.match_id)
                    try:
                        execution_result = future.result()
                    except BaseException as error:
                        buffered[scheduled.request.match_id] = _CompletedMatchAttempt(
                            scheduled, error=error
                        )
                        halt_scheduling = True
                        deferred_error = error
                        continue

                    if execution_result.infrastructure_failure:
                        self._record_infrastructure_failure(
                            scheduled.request, execution_result
                        )
                        if scheduled.request.attempt_number < 3:
                            retry_request = _build_match_request(
                                self._manifest,
                                scheduled.fixture,
                                scheduled.match_ordinal,
                                attempt_number=scheduled.request.attempt_number + 1,
                            )
                            retry = _ScheduledMatchAttempt(
                                scheduled.fixture,
                                scheduled.match_ordinal,
                                retry_request,
                            )
                            self._project_active_matches(
                                records, tuple(active.values()) + (retry,)
                            )
                            self._record_match_attempt_start(retry_request)
                            active[
                                executor.submit(self.match_executor, retry_request)
                            ] = retry
                            retrying_match_ids.add(retry_request.match_id)
                        else:
                            buffered[scheduled.request.match_id] = _CompletedMatchAttempt(
                                scheduled, result=execution_result
                            )
                            halt_scheduling = True
                            deferred_error = (
                                InfrastructureInterventionRequiredError(
                                    scheduled.request.match_id,
                                    scheduled.request.attempt_number,
                                )
                            )
                        continue

                    suspected_team_ids = _suspected_team_ids(execution_result)
                    if suspected_team_ids:
                        telemetry = dict(execution_result.operational_telemetry)
                        telemetry.setdefault(
                            "type", "security_violation_suspected"
                        )
                        telemetry.setdefault("match_id", scheduled.request.match_id)
                        telemetry.setdefault(
                            "attempt_number", scheduled.request.attempt_number
                        )
                        append_operational_telemetry(
                            self.tournament_directory, telemetry
                        )
                    elif execution_result.operational_telemetry:
                        append_operational_telemetry(
                            self.tournament_directory,
                            execution_result.operational_telemetry,
                        )
                    buffered[scheduled.request.match_id] = _CompletedMatchAttempt(
                        scheduled, result=execution_result
                    )
                    if suspected_team_ids:
                        halt_scheduling = True

                self._project_active_matches(records, active.values())

    def _record_match_attempt_start(self, request: MatchExecutionRequest) -> None:
        append_operational_telemetry(
            self.tournament_directory,
            {
                "type": "match_attempt_started",
                "tournament_id": request.tournament_id,
                "fixture_id": request.fixture_id,
                "match_id": request.match_id,
                "attempt_number": request.attempt_number,
            },
        )

    def _record_infrastructure_failure(
        self,
        request: MatchExecutionRequest,
        execution_result: MatchExecutionResult,
    ) -> None:
        telemetry = dict(execution_result.operational_telemetry)
        telemetry.setdefault("type", "match_attempt_failed")
        telemetry.setdefault("match_id", request.match_id)
        telemetry.setdefault("attempt_number", request.attempt_number)
        telemetry.setdefault("infrastructure_failure", True)
        append_operational_telemetry(self.tournament_directory, telemetry)

    def _commit_security_suspicion(
        self,
        records: list[StoredCompetitionRecord],
        state: TournamentState,
        fixture: dict[str, Any],
        match_ordinal: int,
        request: MatchExecutionRequest,
        execution_result: MatchExecutionResult,
        *,
        telemetry_already_recorded: bool,
    ) -> tuple[
        StoredCompetitionRecord,
        list[StoredCompetitionRecord],
        TournamentState,
    ]:
        suspected_team_ids = _suspected_team_ids(execution_result)
        fixture_team_ids = tuple(fixture["team_ids"])
        if any(
            team_id not in fixture_team_ids for team_id in suspected_team_ids
        ):
            raise ValueError(
                "Suspected Security Violation Team does not compete in the "
                "canonical Match"
            )
        if not telemetry_already_recorded:
            telemetry = dict(execution_result.operational_telemetry)
            telemetry.setdefault("type", "security_violation_suspected")
            telemetry.setdefault("match_id", request.match_id)
            telemetry.setdefault("attempt_number", request.attempt_number)
            append_operational_telemetry(self.tournament_directory, telemetry)
        suspicion = append_competition_record(
            self.tournament_directory,
            build_security_violation_suspected_record(
                fixture_id=request.fixture_id,
                match_id=request.match_id,
                match_ordinal=match_ordinal,
                team_ids=(fixture_team_ids[0], fixture_team_ids[1]),
                suspected_team_ids=suspected_team_ids,
                evidence_link=execution_result.evidence_link or "",
                phase=state.phase,
            ),
        )
        incident_records = records + [suspicion]
        incident_state = fold_tournament_state(
            self._manifest, incident_records
        )
        write_scoreboard_projection(
            self.tournament_directory,
            _projection_from_records(
                self._manifest, incident_records, incident_state
            ),
        )
        return suspicion, incident_records, incident_state

    def _commit_terminal_result(
        self,
        records: list[StoredCompetitionRecord],
        fixture: dict[str, Any],
        match_ordinal: int,
        request: MatchExecutionRequest,
        execution_result: MatchExecutionResult,
        *,
        telemetry_already_recorded: bool,
    ) -> tuple[
        StoredCompetitionRecord,
        list[StoredCompetitionRecord],
        TournamentState,
    ]:
        result = _normalize_executor_result(execution_result, fixture)
        if (
            not telemetry_already_recorded
            and execution_result.operational_telemetry
        ):
            append_operational_telemetry(
                self.tournament_directory,
                execution_result.operational_telemetry,
            )
        stored = append_competition_record_to_verified_sequence(
            self.tournament_directory,
            _terminal_record(
                request,
                fixture,
                match_ordinal,
                result,
                execution_result.competitive_outcome,
            ),
            records,
        )
        all_records = records + [stored]
        state_after_match = fold_tournament_state(
            self._manifest, all_records
        )
        all_records, state_after_match = _commit_canonical_transitions_if_ready(
            self.tournament_directory,
            self._manifest,
            all_records,
            state_after_match,
        )
        write_scoreboard_projection(
            self.tournament_directory,
            _projection_from_records(
                self._manifest, all_records, state_after_match
            ),
        )
        return stored, all_records, state_after_match

    def _project_active_matches(
        self,
        records: list[StoredCompetitionRecord],
        active: Iterable[_ScheduledMatchAttempt],
    ) -> None:
        active_values = tuple(active)
        self._set_match_active(bool(active_values))
        projection = _projection_at_match_starts(
            self._manifest,
            records,
            [scheduled.request for scheduled in active_values],
        )
        write_scoreboard_projection(self.tournament_directory, projection)

    def _set_match_active(self, active: bool) -> None:
        update_control_state(
            self.tournament_directory,
            lambda control: {**control, "match_active": active},
        )

    def _claim_parallel_match_boundary(self) -> bool:
        """Claim one Match boundary unless a durable pause won the race."""

        claimed = False

        def claim(control: dict[str, Any]) -> dict[str, Any]:
            nonlocal claimed
            if control["pause_requested"]:
                return control
            control["match_active"] = True
            claimed = True
            return control

        update_control_state(self.tournament_directory, claim)
        return claimed

    def _commit_parallel_prefix(
        self,
        records: list[StoredCompetitionRecord],
        state: TournamentState,
        buffered: dict[str, _CompletedMatchAttempt],
        committed: list[StoredCompetitionRecord],
    ) -> tuple[
        list[StoredCompetitionRecord],
        TournamentState,
        Optional[BaseException],
    ]:
        while True:
            selected = _select_next_match(self._manifest, state)
            if selected is None:
                return records, state, None
            fixture, match_ordinal = selected
            match_id = f"{fixture['fixture_id']}-match-{match_ordinal}"
            completed = buffered.pop(match_id, None)
            if completed is None:
                return records, state, None
            if completed.error is not None:
                return records, state, completed.error
            execution_result = completed.result
            assert execution_result is not None
            request = completed.scheduled.request
            if execution_result.infrastructure_failure:
                return (
                    records,
                    state,
                    InfrastructureInterventionRequiredError(
                        request.match_id, request.attempt_number
                    ),
                )
            suspected_team_ids = _suspected_team_ids(execution_result)
            if suspected_team_ids:
                _suspicion, records, state = self._commit_security_suspicion(
                    records,
                    state,
                    fixture,
                    match_ordinal,
                    request,
                    execution_result,
                    telemetry_already_recorded=True,
                )
                return records, state, None

            stored, records, state = self._commit_terminal_result(
                records,
                fixture,
                match_ordinal,
                request,
                execution_result,
                telemetry_already_recorded=True,
            )
            committed.append(stored)

    def play_next_match(self) -> Optional[StoredCompetitionRecord]:
        """Execute one canonical Match for a Step Mode Tournament."""

        if self.current_mode != "step":
            raise ValueError(
                "Play Next Match requires execution_mode step: a Tournament "
                "sealed in Step Mode or switched to current Step Mode"
            )
        if self._state().is_complete:
            return None
        self._begin_execution(expected_mode="step", allow_intervention=True)
        try:
            return self._play_next_match()
        except InfrastructureInterventionRequiredError:
            self._set_lifecycle("infrastructure_intervention")
            raise
        finally:
            if self._control_state()["lifecycle"] == "running":
                self._set_lifecycle("paused", clear_pause=True)

    def _control_state(self) -> dict[str, Any]:
        control = load_control_state(self.tournament_directory)
        if control is None:
            raise RuntimeError("Tournament control state is missing")
        return control

    def _state(self) -> TournamentState:
        return fold_tournament_state(
            self._manifest,
            load_competition_records(self.tournament_directory),
        )

    def _begin_execution(
        self, *, expected_mode: str, allow_intervention: bool
    ) -> None:
        state = self._state()
        if state.pending_security_ruling is not None:
            raise SecurityRulingRequiredError(state.pending_security_ruling.match_id)
        if state.is_complete:
            raise ValueError("Tournament is already complete")

        def begin(control: dict[str, Any]) -> dict[str, Any]:
            if control["lifecycle"] == "running":
                raise ValueError("Tournament execution is already running")
            if control["current_mode"] != expected_mode:
                raise ValueError(
                    f"Tournament execution mode changed before {expected_mode} "
                    "execution began"
                )
            if (
                control["lifecycle"] == "infrastructure_intervention"
                and not allow_intervention
            ):
                raise ValueError(
                    "Resume is required after infrastructure intervention"
                )
            control["lifecycle"] = "running"
            control["match_active"] = False
            control["pause_requested"] = False
            return control

        update_control_state(self.tournament_directory, begin)

    def _pause_is_requested(self) -> bool:
        return bool(self._control_state()["pause_requested"])

    def _set_lifecycle(self, lifecycle: str, *, clear_pause: bool = False) -> None:
        def set_value(control: dict[str, Any]) -> dict[str, Any]:
            control["lifecycle"] = lifecycle
            if lifecycle != "running":
                control["match_active"] = False
            if clear_pause:
                control["pause_requested"] = False
            return control

        update_control_state(self.tournament_directory, set_value)

    def _claim_match_boundary(self) -> bool:
        """Atomically turn a runnable boundary into an active Match."""

        claimed = False

        def claim(control: dict[str, Any]) -> dict[str, Any]:
            nonlocal claimed
            if (
                control["current_mode"] == "continuous"
                and control["pause_requested"]
            ):
                control["lifecycle"] = "paused"
                control["pause_requested"] = False
                return control
            control["match_active"] = True
            claimed = True
            return control

        update_control_state(self.tournament_directory, claim)
        return claimed

    def _release_match_boundary(self) -> None:
        update_control_state(
            self.tournament_directory,
            lambda control: {**control, "match_active": False},
        )

    def _play_next_match(
        self, *, run_lock_already_held: bool = False
    ) -> Optional[StoredCompetitionRecord]:
        lock = (
            nullcontext()
            if run_lock_already_held
            else TournamentRunLock(self.tournament_directory)
        )
        with lock:
            if not self._claim_match_boundary():
                return None
            try:
                records = load_competition_records(self.tournament_directory)
                state = fold_tournament_state(self._manifest, records)
                if state.pending_security_ruling is not None:
                    raise SecurityRulingRequiredError(
                        state.pending_security_ruling.match_id
                    )
                selected = _select_next_match(self._manifest, state)
                if selected is None:
                    return None
                fixture, match_ordinal = selected
                match_id = f"{fixture['fixture_id']}-match-{match_ordinal}"
                if state.phase is Phase.PLAYOFF and not state.bracket_locked:
                    bracket_lock_record = append_competition_record(
                        self.tournament_directory,
                        {
                            "type": "playoff_bracket_locked",
                            "phase": Phase.PLAYOFF.value,
                            "fixture_id": fixture["fixture_id"],
                            "match_id": match_id,
                        },
                    )
                    records = records + [bracket_lock_record]
                next_attempt_number = _next_attempt_number(
                    self.tournament_directory, match_id
                )
                if next_attempt_number <= 3:
                    attempt_numbers = range(next_attempt_number, 4)
                else:
                    attempt_numbers = (next_attempt_number,)
                for attempt_number in attempt_numbers:
                    request = _build_match_request(
                        self._manifest,
                        fixture,
                        match_ordinal,
                        attempt_number=attempt_number,
                    )
                    write_scoreboard_projection(
                        self.tournament_directory,
                        _projection_at_match_start(
                            self._manifest, records, request
                        ),
                    )
                    self._record_match_attempt_start(request)
                    execution_result = self.match_executor(request)
                    suspected_team_ids = _suspected_team_ids(execution_result)
                    if suspected_team_ids:
                        suspicion, _incident_records, _incident_state = (
                            self._commit_security_suspicion(
                                records,
                                state,
                                fixture,
                                match_ordinal,
                                request,
                                execution_result,
                                telemetry_already_recorded=False,
                            )
                        )
                        return suspicion
                    if execution_result.infrastructure_failure:
                        self._record_infrastructure_failure(
                            request, execution_result
                        )
                        if attempt_number < 3:
                            continue
                        write_scoreboard_projection(
                            self.tournament_directory,
                            _projection_from_records(self._manifest, records),
                        )
                        raise InfrastructureInterventionRequiredError(
                            request.match_id, attempt_number
                        )

                    stored, _all_records, _state_after_match = (
                        self._commit_terminal_result(
                            records,
                            fixture,
                            match_ordinal,
                            request,
                            execution_result,
                            telemetry_already_recorded=False,
                        )
                    )
                    return stored

                # The loop either commits a Match or raises for intervention.
                raise AssertionError("unreachable Match Attempt state")
            finally:
                self._release_match_boundary()

    def abort(
        self,
        *,
        organizer_id: str,
        reason_code: str = OPERATOR_ABORT_REASON,
        note: Optional[str] = None,
    ) -> StoredCompetitionRecord:
        """Terminate an unfinished Tournament without a Tournament Champion."""

        with TournamentRunLock(self.tournament_directory):
            records = load_competition_records(self.tournament_directory)
            state = fold_tournament_state(self._manifest, records)
            if state.is_complete:
                raise ValueError("Tournament is already complete")
            if state.pending_security_ruling is not None:
                raise ValueError(
                    "A pending Security Violation must be ruled on before abort"
                )
            if state.pending_transition_records:
                raise ValueError(
                    "Pending canonical administrative transitions must complete "
                    "before abort"
                )
            aborted = append_competition_record(
                self.tournament_directory,
                build_operator_abort_record(
                    phase=state.phase,
                    organizer_id=organizer_id,
                    reason_code=reason_code,
                    note=note,
                ),
            )
            all_records = records + [aborted]
            aborted_state = fold_tournament_state(self._manifest, all_records)
            write_scoreboard_projection(
                self.tournament_directory,
                _projection_from_records(
                    self._manifest, all_records, aborted_state
                ),
            )
            return aborted

    def confirm_security_violation(
        self,
        *,
        organizer_id: str,
        reason_code: str = "confirmed_prohibited_behavior",
        note: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> StoredCompetitionRecord:
        """Confirm the pending attribution and disqualify the implicated Team."""

        return self._rule_on_security_violation(
            decision="confirmed",
            organizer_id=organizer_id,
            reason_code=reason_code,
            note=note,
            team_id=team_id,
        )

    def reject_security_violation(
        self,
        *,
        organizer_id: str,
        reason_code: str = "attribution_not_confirmed",
        note: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> StoredCompetitionRecord:
        """Reject pending attribution and return the Match to retry policy."""

        return self._rule_on_security_violation(
            decision="rejected",
            organizer_id=organizer_id,
            reason_code=reason_code,
            note=note,
            team_id=team_id,
        )

    def _rule_on_security_violation(
        self,
        *,
        decision: str,
        organizer_id: str,
        reason_code: str,
        note: Optional[str],
        team_id: Optional[str],
    ) -> StoredCompetitionRecord:
        with TournamentRunLock(self.tournament_directory):
            records = load_competition_records(self.tournament_directory)
            state = fold_tournament_state(self._manifest, records)
            pending = state.pending_security_ruling
            if pending is None:
                raise ValueError("No suspected Security Violation awaits a ruling")
            ruling = append_competition_record(
                self.tournament_directory,
                build_security_violation_ruling_record(
                    pending,
                    decision=decision,
                    organizer_id=organizer_id,
                    reason_code=reason_code,
                    note=note,
                    suspected_team_id=team_id,
                ),
            )
            all_records = records + [ruling]
            ruled_state = fold_tournament_state(self._manifest, all_records)
            if decision == "rejected":
                append_operational_telemetry(
                    self.tournament_directory,
                    {
                        "type": "match_attempt_failed",
                        "match_id": pending.match_id,
                        "attempt_number": _latest_attempt_number(
                            self.tournament_directory, pending.match_id
                        ),
                        "infrastructure_failure": True,
                        "reason_code": reason_code,
                    },
                )
            all_records, ruled_state = _commit_canonical_transitions_if_ready(
                self.tournament_directory,
                self._manifest,
                all_records,
                ruled_state,
            )
            write_scoreboard_projection(
                self.tournament_directory,
                _projection_from_records(
                    self._manifest, all_records, ruled_state
                ),
            )
            return ruling


def _commit_canonical_transitions_if_ready(
    tournament_directory: Path,
    manifest: dict[str, Any],
    records: list[StoredCompetitionRecord],
    state: TournamentState,
) -> tuple[list[StoredCompetitionRecord], TournamentState]:
    transitioned_records = records
    transitioned_state = state
    while transitioned_state.pending_transition_records:
        transitioned_records, transitioned_state = _append_and_fold_transition(
            tournament_directory,
            manifest,
            transitioned_records,
            transitioned_state.pending_transition_records[0],
        )
    if (
        transitioned_state.qualifying_phase_complete
        and transitioned_state.phase is Phase.QUALIFYING
        and not transitioned_state.is_complete
    ):
        transitioned_records, transitioned_state = _append_and_fold_transition(
            tournament_directory,
            manifest,
            transitioned_records,
            build_playoff_bracket_record(manifest, transitioned_state.standings),
        )
    if (
        transitioned_state.phase is Phase.PLAYOFF
        and transitioned_state.champion_team_id is None
        and not transitioned_state.ended_without_champion
        and len(transitioned_state.playoff_seeds) == 1
        and not transitioned_state.playoff_fixtures
    ):
        transitioned_records, transitioned_state = _append_and_fold_transition(
            tournament_directory,
            manifest,
            transitioned_records,
            build_sole_eligible_champion_record(
                transitioned_state.playoff_seeds[0].team_id
            ),
        )
    if (
        transitioned_state.phase is Phase.PLAYOFF
        and not transitioned_state.playoff_seeds
        and not transitioned_state.ended_without_champion
    ):
        transitioned_records, transitioned_state = _append_and_fold_transition(
            tournament_directory,
            manifest,
            transitioned_records,
            build_tournament_ended_without_champion_record(),
        )
    if (
        transitioned_state.phase is Phase.PLAYOFF
        and transitioned_state.all_finalists_disqualified
        and transitioned_state.pending_security_ruling is None
        and not transitioned_state.pending_transition_records
        and not transitioned_state.ended_without_champion
    ):
        transitioned_records, transitioned_state = _append_and_fold_transition(
            tournament_directory,
            manifest,
            transitioned_records,
            build_tournament_ended_without_champion_record(
                reason_code=NO_ELIGIBLE_FINALIST_REASON
            ),
        )
    final_winner = transitioned_state.playoff_final_winner
    if (
        transitioned_state.champion_team_id is None
        and not transitioned_state.ended_without_champion
        and final_winner is not None
        and transitioned_state.pending_security_ruling is None
        and not transitioned_state.pending_transition_records
    ):
        transitioned_records, transitioned_state = _append_and_fold_transition(
            tournament_directory,
            manifest,
            transitioned_records,
            build_tournament_champion_record(final_winner),
        )
    return transitioned_records, transitioned_state


def _append_and_fold_transition(
    tournament_directory: Path,
    manifest: dict[str, Any],
    records: list[StoredCompetitionRecord],
    record: Mapping[str, Any],
) -> tuple[list[StoredCompetitionRecord], TournamentState]:
    stored = append_competition_record(tournament_directory, record)
    transitioned_records = records + [stored]
    return transitioned_records, fold_tournament_state(
        manifest, transitioned_records
    )


def tournament_manifest_incompatibilities(
    sealed_manifest: Mapping[str, Any],
    *,
    tournament_id: str,
    tournament_seed: int,
    roster: Iterable[Team],
    config: TournamentConfig = TournamentConfig(),
) -> tuple[str, ...]:
    """Return sealed Manifest fields incompatible with creation inputs."""

    expected_payload = _build_manifest_payload(
        tournament_id=tournament_id,
        tournament_seed=tournament_seed,
        roster=roster,
        config=config,
    )
    return tuple(
        sorted(
            field
            for field in set(sealed_manifest) | set(expected_payload)
            if (
                sealed_manifest.get(field, 1)
                if field == "continuous_parallelism"
                else sealed_manifest.get(field)
            )
            != expected_payload.get(field)
        )
    )


def _build_manifest_payload(
    *,
    tournament_id: str,
    tournament_seed: int,
    roster: Iterable[Team],
    config: TournamentConfig = TournamentConfig(),
) -> dict[str, Any]:
    """Build the validated JSON payload to seal as a Tournament Manifest."""

    teams = tuple(roster)
    _validate_creation_inputs(tournament_id, tournament_seed, teams)
    _validate_tournament_config(config)
    schedule = build_qualifying_schedule(
        (team.team_id for team in teams), tournament_seed
    )
    canonical_roster = tuple(sorted(teams, key=lambda team: team.team_id))
    return {
        "tournament_id": tournament_id,
        "tournament_seed": str(tournament_seed),
        "protocol_version": PROTOCOL_VERSION,
        "seed_derivation_version": SEED_DERIVATION_VERSION,
        "record_schema_version": RECORD_SCHEMA_VERSION,
        "scoreboard_version": SCOREBOARD_VERSION,
        "scheduled_turns_per_match": SCHEDULED_TURNS_PER_MATCH,
        "execution_mode": config.execution_mode,
        "continuous_parallelism": config.continuous_parallelism,
        "execution_profile_version": config.execution_profile_version,
        "match_limits": _serialize_match_limits(config.match_limits),
        "series_format": "best_of_three",
        "rules": manifest_rules(),
        "roster": [_serialize_team(team) for team in canonical_roster],
        "tie_break_keys": {
            team.team_id: str(
                derive_tiebreak_key(tournament_seed, team.team_id)
            )
            for team in canonical_roster
        },
        "qualifying_schedule": [
            _serialize_batch(batch) for batch in schedule
        ],
    }


def _validate_creation_inputs(
    tournament_id: str,
    tournament_seed: int,
    roster: tuple[Team, ...],
) -> None:
    if not isinstance(tournament_id, str) or not tournament_id.strip():
        raise ValueError("Tournament ID must be a non-empty string")
    if not isinstance(tournament_seed, int) or isinstance(tournament_seed, bool):
        raise TypeError("Tournament Seed must be an integer")
    if not 0 <= tournament_seed <= _MAX_U64:
        raise ValueError("Tournament Seed must be an unsigned 64-bit integer")
    if not 4 <= len(roster) <= 32:
        raise ValueError("Roster must contain between 4 and 32 Teams")
    team_ids = [team.team_id for team in roster]
    if len(team_ids) != len(set(team_ids)):
        raise ValueError("Team IDs must be unique within a Tournament")
    for team in roster:
        if _TEAM_ID_PATTERN.fullmatch(team.team_id) is None:
            raise ValueError(f"Malformed Team ID: {team.team_id!r}")
        if not isinstance(team.display_name, str) or not team.display_name.strip():
            raise ValueError("Team Display Name must be a non-empty string")
        _validate_artifact(team.bot_artifact)


def _validate_tournament_config(config: TournamentConfig) -> None:
    if not isinstance(config, TournamentConfig):
        raise TypeError("Tournament config must be a TournamentConfig")
    if config.execution_mode not in ("step", "continuous"):
        raise ValueError("Execution mode must be step or continuous")
    if (
        not isinstance(config.continuous_parallelism, int)
        or isinstance(config.continuous_parallelism, bool)
    ):
        raise TypeError("Continuous Mode parallelism must be an integer")
    if config.continuous_parallelism <= 0:
        raise ValueError("Continuous Mode parallelism must be a positive integer")
    limits = config.match_limits
    if not isinstance(limits, MatchLimits):
        raise TypeError("Match limits must be a MatchLimits value")
    positive_fields = (
        "first_move_timeout_ms",
        "move_timeout_ms",
        "total_timeout_ms",
        "stderr_limit_bytes",
        "stdout_limit_bytes",
        "cpu_limit_ms",
        "memory_limit_bytes",
        "process_limit",
        "open_file_limit",
        "cpu_quota_millis_per_second",
    )
    for field in positive_fields:
        value = getattr(limits, field)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"{field} must be a positive integer")
    if limits.cpu_limit_ms % 1000 != 0:
        raise ValueError("cpu_limit_ms must be a whole number of seconds")
    if (
        not isinstance(limits.filesystem_write_limit_bytes, int)
        or isinstance(limits.filesystem_write_limit_bytes, bool)
        or limits.filesystem_write_limit_bytes <= 0
    ):
        raise ValueError(
            "filesystem_write_limit_bytes must be a positive integer"
        )
    if limits.network_access_allowed is not False:
        raise ValueError("network_access_allowed must be false")
    if config.execution_profile_version != CONTAINER_ISOLATION_PROFILE_VERSION:
        raise ValueError("Unsupported execution_profile_version")


def _validate_artifact(artifact: BotArtifactManifest) -> None:
    if not isinstance(artifact, BotArtifactManifest):
        raise ValueError("Every Team requires one Bot Artifact Manifest")
    if _DIGEST_PATTERN.fullmatch(artifact.artifact_digest) is None:
        raise ValueError("Bot Artifact digest must be a SHA-256 digest")
    if _LANGUAGE_ID_PATTERN.fullmatch(artifact.language_id) is None:
        raise ValueError("Bot Artifact language ID is invalid")
    if not artifact.wrapper_version.strip():
        raise ValueError("Bot Artifact wrapper version is required")
    if _DIGEST_PATTERN.fullmatch(artifact.runtime_digest) is None:
        raise ValueError("Bot Artifact runtime digest is invalid")
    if (
        not isinstance(artifact.entrypoint, tuple)
        or not artifact.entrypoint
        or any(
            not isinstance(argument, str) or not argument or "\x00" in argument
            for argument in artifact.entrypoint
        )
    ):
        raise ValueError("Bot Artifact entrypoint must be an argument array")


def _verify_compatibility(manifest: dict[str, Any]) -> None:
    expected_values = {
        "protocol_version": PROTOCOL_VERSION,
        "seed_derivation_version": SEED_DERIVATION_VERSION,
        "record_schema_version": RECORD_SCHEMA_VERSION,
        "scoreboard_version": SCOREBOARD_VERSION,
        "scheduled_turns_per_match": SCHEDULED_TURNS_PER_MATCH,
        "execution_profile_version": CONTAINER_ISOLATION_PROFILE_VERSION,
        "series_format": "best_of_three",
        "rules": manifest_rules(),
    }
    for field, expected in expected_values.items():
        actual = manifest.get(field)
        if actual != expected:
            raise TournamentCompatibilityError(field, expected, actual)
    parallelism = manifest.get("continuous_parallelism", 1)
    if (
        not isinstance(parallelism, int)
        or isinstance(parallelism, bool)
        or parallelism <= 0
    ):
        raise TournamentCompatibilityError(
            "continuous_parallelism", "positive integer", parallelism
        )


def _verify_artifact_digests(
    manifest: dict[str, Any],
    verifier: Callable[[str, str], bool],
) -> None:
    for team in manifest["roster"]:
        team_id = team["team_id"]
        artifact_digest = team["bot_artifact"]["artifact_digest"]
        if not verifier(team_id, artifact_digest):
            raise ArtifactDigestVerificationError(team_id, artifact_digest)


def _serialize_team(team: Team) -> dict[str, Any]:
    artifact = team.bot_artifact
    return {
        "team_id": team.team_id,
        "display_name": team.display_name,
        "bot_artifact": {
            "artifact_digest": artifact.artifact_digest,
            "language_id": artifact.language_id,
            "wrapper_version": artifact.wrapper_version,
            "runtime_digest": artifact.runtime_digest,
            "entrypoint": list(artifact.entrypoint),
        },
    }


def _serialize_match_limits(limits: MatchLimits) -> dict[str, Any]:
    return {
        "first_move_timeout_ms": limits.first_move_timeout_ms,
        "move_timeout_ms": limits.move_timeout_ms,
        "total_timeout_ms": limits.total_timeout_ms,
        "stderr_limit_bytes": limits.stderr_limit_bytes,
        "stdout_limit_bytes": limits.stdout_limit_bytes,
        "cpu_limit_ms": limits.cpu_limit_ms,
        "memory_limit_bytes": limits.memory_limit_bytes,
        "process_limit": limits.process_limit,
        "open_file_limit": limits.open_file_limit,
        "cpu_quota_millis_per_second": limits.cpu_quota_millis_per_second,
        "filesystem_write_limit_bytes": limits.filesystem_write_limit_bytes,
        "network_access_allowed": limits.network_access_allowed,
    }


def _serialize_fixture(fixture: Fixture) -> dict[str, Any]:
    return {
        "fixture_id": fixture.fixture_id,
        "ordinal": fixture.ordinal,
        "batch_ordinal": fixture.batch_ordinal,
        "team_ids": list(fixture.team_ids),
        "fixture_seed": str(fixture.fixture_seed),
    }


def _serialize_batch(batch: FixtureBatch) -> dict[str, Any]:
    return {
        "ordinal": batch.ordinal,
        "bye_team_id": batch.bye_team_id,
        "fixtures": [_serialize_fixture(fixture) for fixture in batch.fixtures],
    }


def _initial_projection(manifest: dict[str, Any]) -> dict[str, Any]:
    fixtures = [
        fixture
        for batch in manifest["qualifying_schedule"]
        for fixture in batch["fixtures"]
    ]
    return {
        "version": SCOREBOARD_VERSION,
        "tournament_id": manifest["tournament_id"],
        "status": "paused",
        "phase": "qualifying",
        "teams": [
            {
                "team_id": team["team_id"],
                "display_name": team["display_name"],
            }
            for team in manifest["roster"]
        ],
        "fixtures": [
            {
                "fixture_id": fixture["fixture_id"],
                "team_ids": fixture["team_ids"],
                "status": "scheduled",
                "matches": [],
            }
            for fixture in fixtures
        ],
        "standings": _standing_projection(
            fold_tournament_state(manifest, ()).standings
        ),
        "champion": None,
    }


def _manifest_fixtures(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        fixture
        for batch in manifest["qualifying_schedule"]
        for fixture in batch["fixtures"]
    ]


def _select_next_match(
    manifest: dict[str, Any],
    state: TournamentState,
) -> Optional[tuple[dict[str, Any], int]]:
    selected = state.next_qualifying_match
    if selected is None:
        selected = state.next_playoff_match
    if selected is None:
        return None
    for fixture in _manifest_fixtures(manifest):
        if fixture["fixture_id"] == selected.fixture_id:
            return fixture, selected.match_ordinal
    for fixture in state.playoff_fixtures:
        if fixture.fixture_id == selected.fixture_id:
            return {
                "fixture_id": fixture.fixture_id,
                "team_ids": list(selected.team_ids),
                "fixture_seed": str(fixture.fixture_seed),
                "phase": Phase.PLAYOFF.value,
            }, selected.match_ordinal
    raise AssertionError("Folded state selected a Fixture outside the Manifest")


def _runnable_matches(
    manifest: dict[str, Any], state: TournamentState
) -> list[tuple[dict[str, Any], int]]:
    """Return schedule-ordered next Matches whose Series dependencies are met."""

    if (
        state.is_complete
        or state.pending_security_ruling is not None
        or state.pending_transition_records
    ):
        return []
    disqualified = set(state.disqualified_team_ids)
    runnable: list[tuple[dict[str, Any], int]] = []
    if state.phase is Phase.QUALIFYING:
        for fixture, series in zip(
            _manifest_fixtures(manifest), state.qualifying_series
        ):
            if series.is_complete or set(fixture["team_ids"]) & disqualified:
                continue
            runnable.append((fixture, series.match_count + 1))
        return runnable

    for fixture, series in zip(state.playoff_fixtures, state.playoff_series):
        if series.is_complete or None in fixture.team_ids:
            continue
        team_ids = (fixture.team_ids[0], fixture.team_ids[1])
        if set(team_ids) & disqualified:
            continue
        runnable.append(
            (
                {
                    "fixture_id": fixture.fixture_id,
                    "team_ids": list(team_ids),
                    "fixture_seed": str(fixture.fixture_seed),
                    "phase": Phase.PLAYOFF.value,
                },
                series.match_count + 1,
            )
        )
    return runnable


def _suspected_team_ids(
    execution_result: MatchExecutionResult,
) -> tuple[str, ...]:
    return execution_result.suspected_security_violation_team_ids or (
        (execution_result.suspected_security_violation_team_id,)
        if execution_result.suspected_security_violation_team_id is not None
        else ()
    )


def _next_attempt_number(
    tournament_directory: Path, match_id: str
) -> int:
    latest_attempt = 0
    for telemetry in load_operational_telemetry(tournament_directory):
        if telemetry.get("match_id") != match_id:
            continue
        attempt_number = telemetry.get("attempt_number")
        if (
            not isinstance(attempt_number, int)
            or isinstance(attempt_number, bool)
            or attempt_number < 1
        ):
            raise ValueError(
                f"Operational Telemetry has an invalid Match Attempt for {match_id}"
            )
        latest_attempt = max(latest_attempt, attempt_number)
    return latest_attempt + 1


def _latest_attempt_number(tournament_directory: Path, match_id: str) -> int:
    attempt_number = _next_attempt_number(tournament_directory, match_id) - 1
    if attempt_number < 1:
        raise ValueError(f"No Match Attempt exists for {match_id}")
    return attempt_number


def _build_match_request(
    manifest: dict[str, Any],
    fixture: dict[str, Any],
    match_ordinal: int,
    *,
    attempt_number: int,
) -> MatchExecutionRequest:
    fixture_seed = int(fixture["fixture_seed"])
    match_seed = derive_match_seed(fixture_seed, match_ordinal)
    team_ids = tuple(fixture["team_ids"])
    assert len(team_ids) == 2
    positions = bot_positions(
        fixture_seed, match_ordinal, team_ids[0], team_ids[1]
    )
    artifacts = {
        team["team_id"]: _artifact_from_manifest(team["bot_artifact"])
        for team in manifest["roster"]
    }
    bot_seeds = {
        team_id: derive_bot_seed(match_seed, team_id) for team_id in team_ids
    }
    limits = manifest["match_limits"]
    return MatchExecutionRequest(
        tournament_id=manifest["tournament_id"],
        fixture_id=fixture["fixture_id"],
        series_id=f"{fixture['fixture_id']}-series",
        match_id=f"{fixture['fixture_id']}-match-{match_ordinal}",
        attempt_number=attempt_number,
        team_a_id=positions.team_a_id,
        team_b_id=positions.team_b_id,
        artifact_digest_a=artifacts[positions.team_a_id].artifact_digest,
        artifact_digest_b=artifacts[positions.team_b_id].artifact_digest,
        match_seed=match_seed,
        bot_visible_seed_a=bot_seeds[positions.team_a_id],
        bot_visible_seed_b=bot_seeds[positions.team_b_id],
        protocol_version=manifest["protocol_version"],
        scheduled_turns=manifest["scheduled_turns_per_match"],
        first_move_timeout_ms=limits["first_move_timeout_ms"],
        move_timeout_ms=limits["move_timeout_ms"],
        total_timeout_ms=limits["total_timeout_ms"],
        stderr_limit_bytes=limits["stderr_limit_bytes"],
        stdout_limit_bytes=limits["stdout_limit_bytes"],
        cpu_limit_ms=limits["cpu_limit_ms"],
        memory_limit_bytes=limits["memory_limit_bytes"],
        process_limit=limits["process_limit"],
        open_file_limit=limits["open_file_limit"],
        cpu_quota_millis_per_second=limits["cpu_quota_millis_per_second"],
        filesystem_write_limit_bytes=limits["filesystem_write_limit_bytes"],
        network_access_allowed=limits["network_access_allowed"],
        execution_profile_version=manifest["execution_profile_version"],
    )


def _artifact_from_manifest(value: dict[str, Any]) -> BotArtifactManifest:
    return BotArtifactManifest(
        artifact_digest=value["artifact_digest"],
        language_id=value["language_id"],
        wrapper_version=value["wrapper_version"],
        runtime_digest=value["runtime_digest"],
        entrypoint=tuple(value["entrypoint"]),
    )


def _normalize_executor_result(
    execution_result: MatchExecutionResult,
    fixture: dict[str, Any],
) -> MatchResult:
    if not isinstance(execution_result, MatchExecutionResult):
        raise TypeError("Match executor must return a MatchExecutionResult")
    if execution_result.infrastructure_failure:
        raise RuntimeError("Infrastructure Failure did not produce a Match result")
    outcome = execution_result.competitive_outcome
    if not isinstance(outcome, dict):
        raise ValueError("Match executor returned no competitive outcome")

    team_one_id, team_two_id = fixture["team_ids"]
    score = outcome.get("score")
    faults = outcome.get("faults")
    if not isinstance(score, dict) or not isinstance(faults, dict):
        raise ValueError("Competitive outcome is missing score or fault facts")
    try:
        round_wins = (int(score[team_one_id]), int(score[team_two_id]))
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Competitive score does not match Fixture Teams") from error

    outcome_kind = MatchOutcome(outcome.get("outcome"))
    if outcome_kind is MatchOutcome.DOUBLE_FORFEIT:
        return MatchResult.double_forfeit(
            team_one_id,
            team_two_id,
            completed_round_wins=round_wins,
        )
    if outcome_kind is MatchOutcome.DRAW:
        return MatchResult.draw(
            team_one_id, team_two_id, round_wins=round_wins
        )

    faulting_teams = [
        team_id
        for team_id in (team_one_id, team_two_id)
        if faults.get(team_id) is not None
    ]
    if len(faulting_teams) == 1:
        return MatchResult.protocol_forfeit(
            team_one_id,
            team_two_id,
            faulting_team_id=faulting_teams[0],
            completed_round_wins=round_wins,
        )
    if faulting_teams:
        raise ValueError("Two Team faults must be a Double Forfeit")
    winner_team_id = outcome.get("winner_team_id")
    if not isinstance(winner_team_id, str):
        raise ValueError("Winning Match outcome requires a Team winner")
    return MatchResult.win(
        team_one_id,
        team_two_id,
        winner_team_id,
        round_wins=round_wins,
    )


def _terminal_record(
    request: MatchExecutionRequest,
    fixture: dict[str, Any],
    match_ordinal: int,
    result: MatchResult,
    competitive_outcome: Optional[dict[str, object]],
) -> dict[str, Any]:
    if competitive_outcome is None:
        raise ValueError("Terminal Match requires a competitive outcome")
    moves, rounds, faults = _competitive_details(
        competitive_outcome, fixture["team_ids"]
    )
    team_one_id, team_two_id = fixture["team_ids"]
    return {
        "type": "match_terminal",
        "phase": fixture.get("phase", Phase.QUALIFYING.value),
        "fixture_id": request.fixture_id,
        "match_id": request.match_id,
        "match_ordinal": match_ordinal,
        "team_ids": [team_one_id, team_two_id],
        "outcome": result.outcome.value,
        "winner_team_id": result.winner,
        "round_wins": result.round_wins,
        "protocol_forfeit_team_id": result.protocol_forfeit_team_id,
        "moves": moves,
        "rounds": rounds,
        "faults": faults,
        "match_seed": str(request.match_seed),
        "bot_positions": {
            "a": request.team_a_id,
            "b": request.team_b_id,
        },
        "bot_visible_seeds": {
            request.team_a_id: str(request.bot_visible_seed_a),
            request.team_b_id: str(request.bot_visible_seed_b),
        },
        "artifact_digests": {
            request.team_a_id: request.artifact_digest_a,
            request.team_b_id: request.artifact_digest_b,
        },
    }


def _competitive_details(
    outcome: dict[str, object], team_ids: list[str]
) -> tuple[dict[str, str], list[dict[str, object]], dict[str, object]]:
    raw_moves = outcome.get("moves")
    raw_rounds = outcome.get("rounds")
    raw_faults = outcome.get("faults")
    if not isinstance(raw_moves, dict) or not isinstance(raw_rounds, list):
        raise ValueError("Competitive outcome is missing completed play facts")
    if not isinstance(raw_faults, dict):
        raise ValueError("Competitive outcome is missing normalized faults")

    moves: dict[str, str] = {}
    faults: dict[str, object] = {}
    for team_id in team_ids:
        move_history = raw_moves.get(team_id)
        if not isinstance(move_history, str):
            raise ValueError("Completed moves do not match Fixture Teams")
        moves[team_id] = move_history
        fault = raw_faults.get(team_id)
        if fault is None:
            faults[team_id] = None
            continue
        if not isinstance(fault, dict):
            raise ValueError("Normalized fault must be an object or null")
        kind = fault.get("kind")
        turn = fault.get("turn")
        if (
            not isinstance(kind, str)
            or not isinstance(turn, int)
            or isinstance(turn, bool)
        ):
            raise ValueError("Normalized fault requires kind and Turn")
        faults[team_id] = {"kind": kind, "turn": turn}

    rounds: list[dict[str, object]] = []
    for raw_round in raw_rounds:
        if not isinstance(raw_round, dict):
            raise ValueError("Completed Round must be an object")
        turn = raw_round.get("turn")
        round_moves = raw_round.get("moves")
        winner_team_id = raw_round.get("winner_team_id")
        if not isinstance(turn, int) or isinstance(turn, bool):
            raise ValueError("Completed Round requires a numeric Turn")
        if not isinstance(round_moves, dict) or any(
            not isinstance(round_moves.get(team_id), str)
            for team_id in team_ids
        ):
            raise ValueError("Completed Round moves do not match Fixture Teams")
        if winner_team_id is not None and winner_team_id not in team_ids:
            raise ValueError("Completed Round winner does not match Fixture Teams")
        rounds.append(
            {
                "turn": turn,
                "moves": {
                    team_id: round_moves[team_id] for team_id in team_ids
                },
                "winner_team_id": winner_team_id,
            }
        )
    return moves, rounds, faults


def _projection_from_records(
    manifest: dict[str, Any],
    records: list[StoredCompetitionRecord],
    state: Optional[TournamentState] = None,
) -> dict[str, Any]:
    folded = state or fold_tournament_state(manifest, records)
    projection = _initial_projection(manifest)
    terminal_by_fixture: dict[str, list[dict[str, Any]]] = {}
    replacement_by_fixture: dict[str, dict[str, Any]] = {}
    for stored in records:
        if stored.record.get("type") == "match_terminal":
            terminal_by_fixture.setdefault(
                stored.record["fixture_id"], []
            ).append(stored.record)
        elif stored.record.get("type") == "playoff_bracket_position_replaced":
            replacement_by_fixture[stored.record["fixture_id"]] = stored.record

    for fixture_projection, series in zip(
        projection["fixtures"], folded.qualifying_series
    ):
        _apply_series_projection(
            fixture_projection, series, terminal_by_fixture
        )
        if (
            not series.is_complete
            and {
                series.team_one_id,
                series.team_two_id,
            }
            <= set(folded.disqualified_team_ids)
        ):
            fixture_projection["status"] = "skipped"
            fixture_projection["skip_reason"] = "teams_disqualified"
    projection["standings"] = _standing_projection(folded.standings)
    projection["phase"] = folded.phase.value
    projection["champion"] = folded.champion_team_id
    for team in projection["teams"]:
        if team["team_id"] in folded.disqualified_team_ids:
            team["eligible"] = False
            team["status"] = "disqualified"
    if folded.pending_security_ruling is not None:
        pending = folded.pending_security_ruling
        projection["status"] = "awaiting_security_ruling"
        projection["security_review"] = {
            "fixture_id": pending.fixture_id,
            "match_id": pending.match_id,
            **(
                {"suspected_team_id": pending.suspected_team_ids[0]}
                if len(pending.suspected_team_ids) == 1
                else {"suspected_team_ids": list(pending.suspected_team_ids)}
            ),
        }
    if folded.was_aborted:
        assert folded.operator_abort is not None
        projection["status"] = "aborted"
        projection["completion_reason"] = folded.operator_abort.reason_code
        projection["operator_abort"] = {
            "organizer_id": folded.operator_abort.organizer_id,
            "reason_code": folded.operator_abort.reason_code,
            "note": folded.operator_abort.note,
        }
    elif folded.is_complete:
        projection["status"] = "complete"
    if folded.ended_without_champion:
        projection["completion_reason"] = (
            NO_ELIGIBLE_FINALIST_REASON
            if folded.all_finalists_disqualified
            else NO_ELIGIBLE_TEAMS_REASON
        )
    if folded.phase.value == "playoff":
        projection["bracket"] = {
            "locked": folded.bracket_locked,
            "seeds": [
                {"seed": seed.seed, "team_id": seed.team_id}
                for seed in folded.playoff_seeds
            ],
            "fixtures": [
                {
                    "fixture_id": fixture.fixture_id,
                    "stage": fixture.stage.value,
                    "team_ids": list(fixture.team_ids),
                    "fixture_seed": str(fixture.fixture_seed),
                    "status": "scheduled",
                    "matches": [],
                }
                for fixture in folded.playoff_fixtures
            ],
        }
        for fixture_projection, series in zip(
            projection["bracket"]["fixtures"], folded.playoff_series
        ):
            _apply_series_projection(
                fixture_projection, series, terminal_by_fixture
            )
        for fixture_projection in projection["bracket"]["fixtures"]:
            replacement = replacement_by_fixture.get(
                fixture_projection["fixture_id"]
            )
            if replacement is not None:
                fixture_projection["bracket_position_replacement"] = {
                    "disqualified_team_id": replacement["disqualified_team_id"],
                    "reinstated_team_id": replacement["reinstated_team_id"],
                    "source_fixture_id": replacement["source_fixture_id"],
                    "reason_code": replacement["reason_code"],
                }
            if (
                folded.champion_team_id is not None
                and fixture_projection["stage"] == "final"
                and folded.champion_team_id in fixture_projection["team_ids"]
                and fixture_projection["status"] == "scheduled"
            ):
                fixture_projection["status"] = "complete"
                fixture_projection["resolved_team_id"] = (
                    folded.champion_team_id
                )
    return projection


def _apply_series_projection(
    fixture_projection: dict[str, Any],
    series: Series,
    terminal_by_fixture: dict[str, list[dict[str, Any]]],
) -> None:
    fixture_records = sorted(
        terminal_by_fixture.get(fixture_projection["fixture_id"], ()),
        key=lambda record: record["match_ordinal"],
    )
    if not fixture_records and series.administrative_winner_id is None:
        return
    fixture_projection["status"] = (
        "complete" if series.is_complete else "in_progress"
    )
    if series.administrative_winner_id is not None:
        fixture_projection["administrative_series_win"] = {
            "winner_team_id": series.administrative_winner_id,
            "reason_code": "opponent_disqualified",
        }
    fixture_projection["matches"] = [
        {
            "match_id": record["match_id"],
            "outcome": record["outcome"],
            "winner_team_id": record["winner_team_id"],
        }
        for record in fixture_records
    ]


def _projection_at_match_start(
    manifest: dict[str, Any],
    records: list[StoredCompetitionRecord],
    request: MatchExecutionRequest,
) -> dict[str, Any]:
    projection = _projection_from_records(manifest, records)
    projection["status"] = "running"
    fixtures = projection["fixtures"] + projection.get("bracket", {}).get(
        "fixtures", []
    )
    for fixture in fixtures:
        if fixture["fixture_id"] == request.fixture_id:
            fixture["status"] = "active"
            fixture["active_match_id"] = request.match_id
            break
    return projection


def _projection_at_match_starts(
    manifest: dict[str, Any],
    records: list[StoredCompetitionRecord],
    requests: Iterable[MatchExecutionRequest],
) -> dict[str, Any]:
    projection = _projection_from_records(manifest, records)
    request_values = tuple(requests)
    if not request_values:
        return projection
    projection["status"] = "running"
    request_by_fixture = {
        request.fixture_id: request for request in request_values
    }
    fixtures = projection["fixtures"] + projection.get("bracket", {}).get(
        "fixtures", []
    )
    for fixture in fixtures:
        request = request_by_fixture.get(fixture["fixture_id"])
        if request is not None:
            fixture["status"] = "active"
            fixture["active_match_id"] = request.match_id
    return projection


def _standing_projection(
    standings: Iterable[Standing],
) -> list[dict[str, Any]]:
    return [
        {
            "team_id": standing.team_id,
            "standing_points": standing.standing_points,
            "series_wins": standing.series_wins,
            "match_differential": standing.match_differential,
            "round_differential": standing.round_differential,
            "protocol_fault_forfeits": standing.protocol_fault_forfeits,
            "tie_break_key": str(standing.tie_break_key),
        }
        for standing in standings
    ]
