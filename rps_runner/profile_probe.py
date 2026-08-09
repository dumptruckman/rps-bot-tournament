from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Mapping, Optional, Sequence

from rps_runner.engine.container_session import ContainerIsolationProfile
from rps_runner.execution_profile import INITIAL_EXECUTION_PROFILE
from rps_runner.language_environment import CatalogError, load_catalog


class ProfileProbeFailure(RuntimeError):
    """The native Python execution-profile probe could not produce evidence."""


_PROBE_PROGRAM = r"""
import hashlib
import json
import os
import resource
import tempfile
import threading
import time

allocation = bytearray(8 * 1024 * 1024)
with tempfile.NamedTemporaryFile(dir='/tmp') as temporary:
    temporary.write(b'x' * (1024 * 1024))
    temporary.flush()
    descriptors = [open('/dev/null', 'rb') for _ in range(24)]
    ready = threading.Barrier(9)
    release = threading.Event()
    def hold_thread():
        ready.wait()
        release.wait()
    threads = [threading.Thread(target=hold_thread) for _ in range(8)]
    for thread in threads:
        thread.start()
    ready.wait()
    peak_open_files = len(os.listdir('/proc/self/fd'))
    peak_threads = int(next(
        line.split(':', 1)[1] for line in open('/proc/self/status')
        if line.startswith('Threads:')
    ))
    release.set()
    for thread in threads:
        thread.join()
    for descriptor in descriptors:
        descriptor.close()

started = time.process_time_ns()
value = b'rps-profile-probe-v1'
for _ in range(200000):
    value = hashlib.sha256(value).digest()
cpu_probe_ms = (time.process_time_ns() - started) / 1000000
numeric_pids = sum(name.isdigit() for name in os.listdir('/proc'))
print(json.dumps({
    'python_version': '.'.join(map(str, __import__('sys').version_info[:3])),
    'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
    'cpu_probe_ms': round(cpu_probe_ms, 3),
    'visible_pids': numeric_pids,
    'peak_threads': peak_threads,
    'peak_open_files': peak_open_files,
    'temporary_filesystem_bytes': 1048576,
}, sort_keys=True))
""".strip()


def _run(
    arguments: Sequence[str], description: str, timeout: float
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            list(arguments), capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ProfileProbeFailure(description + " failed: " + str(error)) from error
    if completed.returncode != 0:
        diagnostic = (completed.stderr or completed.stdout).strip()
        raise ProfileProbeFailure(
            description
            + " failed with exit code "
            + str(completed.returncode)
            + (": " + diagnostic[:1000] if diagnostic else "")
        )
    return completed


def _runtime_reference(catalog_path: Path, target_platform: str) -> tuple[str, str]:
    catalog = load_catalog(catalog_path)
    asset = catalog.environment("python").assets["base_runtime"]
    try:
        definition = json.loads(asset.content)
        selected = definition["platforms"][target_platform]
        reference = selected["image"]
        version = selected["version"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ProfileProbeFailure(
            "catalog has no valid Python runtime for " + target_platform
        ) from error
    if not isinstance(reference, str) or "@sha256:" not in reference:
        raise ProfileProbeFailure("Python runtime reference is not immutable")
    return reference, str(version) + "@" + reference.rsplit("@", 1)[1]


def measure_python_runtime(
    catalog_path: Path, target_platform: str
) -> Mapping[str, Any]:
    if target_platform not in ("linux/arm64", "linux/amd64"):
        raise ProfileProbeFailure("platform must be linux/arm64 or linux/amd64")
    profile = INITIAL_EXECUTION_PROFILE
    reported_native = _run(
        ["docker", "info", "--format", "{{.OSType}}/{{.Architecture}}"],
        "Docker engine inspection",
        10.0,
    ).stdout.strip()
    native = {
        "linux/aarch64": "linux/arm64",
        "linux/x86_64": "linux/amd64",
    }.get(reported_native, reported_native)
    if native != target_platform:
        raise ProfileProbeFailure(
            "profile evidence requires native "
            + target_platform
            + " execution; Docker reports "
            + repr(reported_native)
            + ", so emulation is not accepted"
        )
    reference, runtime_identity = _runtime_reference(catalog_path, target_platform)
    inspected = _run(
        ["docker", "image", "inspect", reference],
        "pinned Python runtime inspection",
        10.0,
    )
    try:
        details = json.loads(inspected.stdout)
        image = details[0]
    except (json.JSONDecodeError, IndexError, TypeError) as error:
        raise ProfileProbeFailure(
            "Docker returned invalid runtime inspection data"
        ) from error
    observed = str(image.get("Os", "")) + "/" + str(image.get("Architecture", ""))
    if observed != target_platform:
        raise ProfileProbeFailure(
            "pinned Python runtime is "
            + repr(observed)
            + ", expected "
            + repr(target_platform)
        )
    digest = reference.rsplit("@", 1)[1]
    repo_digests = image.get("RepoDigests")
    if image.get("Id") != digest and not (
        isinstance(repo_digests, list)
        and any(
            isinstance(value, str) and value.endswith("@" + digest)
            for value in repo_digests
        )
    ):
        raise ProfileProbeFailure(
            "local Python runtime does not match its pinned platform digest"
        )

    isolation = ContainerIsolationProfile(
        version=profile.version,
        cpu_millis_per_second=profile.cpu_limit_ms,
        memory_limit_bytes=profile.memory_limit_bytes,
        process_limit=profile.process_limit,
        open_file_limit=profile.open_file_limit,
        writable_filesystem_limit_bytes=profile.filesystem_write_limit_bytes,
        cpu_quota_millis_per_second=profile.cpu_quota_millis_per_second,
    )
    base_command = [
        "docker",
        "run",
        "--rm",
        "--platform",
        target_platform,
        *isolation.create_arguments(()),
        reference,
    ]
    startup_started = time.monotonic_ns()
    _run(
        [*base_command, "python3", "-c", "pass"],
        "native Python startup probe",
        profile.startup_timeout_seconds,
    )
    startup_ms = round((time.monotonic_ns() - startup_started) / 1_000_000, 3)
    command = [
        *base_command,
        "python3",
        "-c",
        _PROBE_PROGRAM,
    ]
    completed = _run(
        command, "native Python runtime probe", profile.startup_timeout_seconds
    )
    try:
        measurements = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ProfileProbeFailure(
            "native Python runtime probe returned invalid JSON"
        ) from error
    if not isinstance(measurements, dict):
        raise ProfileProbeFailure(
            "native Python runtime probe did not return an object"
        )
    measurements["startup_ms"] = startup_ms
    return {
        "report_format_version": "python-profile-probe-v1",
        "platform": target_platform,
        "native_execution": True,
        "emulation_accepted": False,
        "runtime_reference": reference,
        "runtime_identity": runtime_identity,
        "profile_identity": profile.identity,
        "profile": profile.as_mapping(),
        "measurements": measurements,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rps-profile-probe",
        description="Measure Python under the published profile on native Docker",
    )
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument(
        "--platform", required=True, choices=("linux/arm64", "linux/amd64")
    )
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(arguments: Optional[list[str]] = None) -> int:
    options = build_parser().parse_args(arguments)
    try:
        report = measure_python_runtime(options.catalog, options.platform)
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    except (CatalogError, OSError, ProfileProbeFailure, ValueError) as error:
        print("rps-profile-probe: " + str(error), file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
