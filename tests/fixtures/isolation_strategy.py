from __future__ import annotations

import os
from pathlib import Path
import resource
import socket
import subprocess
import sys


EXPECTED_ENVIRONMENT = {
    "HOME": "/tmp",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "RPS_PROTOCOL_VERSION": "1",
    "RPS_ROUNDS": "300",
    "RPS_SEED": "111",
    "TMPDIR": "/tmp",
    "TZ": "UTC",
}


def blocked(operation):
    try:
        operation()
    except (OSError, PermissionError):
        return True
    return False


def status_values():
    values = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        if ":" in line:
            name, value = line.split(":", 1)
            values[name] = value.strip()
    return values


def network_is_private():
    interfaces = {path.name for path in Path("/sys/class/net").iterdir()}
    if interfaces != {"lo"}:
        return False
    connection = socket.socket()
    connection.settimeout(0.1)
    try:
        return blocked(lambda: connection.connect(("1.1.1.1", 53)))
    finally:
        connection.close()


def cgroup_value(name):
    path = Path("/sys/fs/cgroup") / name
    return path.read_text().strip() if path.exists() else None


def capability_use_is_blocked():
    return blocked(
        lambda: socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
    )


def docker_access_is_blocked():
    connection = socket.socket(socket.AF_UNIX)
    try:
        return blocked(lambda: connection.connect("/var/run/docker.sock"))
    finally:
        connection.close()


def open_file_escape_is_blocked():
    descriptors = []
    try:
        for _ in range(80):
            descriptors.append(open("/dev/null", "rb"))
    except OSError:
        return True
    finally:
        for descriptor in descriptors:
            descriptor.close()
    return False


def process_escape_is_blocked():
    processes = []
    try:
        for _ in range(80):
            processes.append(
                subprocess.Popen(
                    [sys.executable, "-c", "import time; time.sleep(5)"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
    except OSError:
        return True
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait()
    return False


def subprocess_resource_escape_is_blocked(program):
    completed = subprocess.run(
        [sys.executable, "-c", program],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=5,
    )
    return completed.returncode != 0


def temporary_filesystem_overflow_is_blocked():
    target = Path("/tmp/isolation-overflow")
    try:
        with target.open("wb") as output:
            for _ in range(17):
                output.write(b"x" * 1_048_576)
    except OSError:
        return True
    finally:
        target.unlink(missing_ok=True)
    return False


STATUS = status_values()
CHECKS = {
    "capabilities-dropped": (
        int(STATUS["CapEff"], 16) == 0 and capability_use_is_blocked()
    ),
    "cpu-bounded": cgroup_value("cpu.max") == "100000 100000",
    "docker-absent": (
        not Path("/var/run/docker.sock").exists() and docker_access_is_blocked()
    ),
    "environment-allowlisted": dict(os.environ) == EXPECTED_ENVIRONMENT,
    "filesystem-private": (
        not Path("/host").exists()
        and blocked(lambda: Path("/host/isolation-sentinel").read_bytes())
    ),
    "hostname-fixed": socket.gethostname() == "rps-bot",
    "memory-bounded": (
        cgroup_value("memory.max") == "268435456"
        and subprocess_resource_escape_is_blocked("x = bytearray(300_000_000)")
    ),
    "network-private": network_is_private(),
    "no-privilege-escalation": STATUS["NoNewPrivs"] == "1",
    "privilege-escalation-blocked": blocked(lambda: os.setuid(0)),
    "non-root": os.getuid() == 65532 and os.getgid() == 65532,
    "open-files-bounded": resource.getrlimit(resource.RLIMIT_NOFILE) == (64, 64),
    "open-file-escape-blocked": open_file_escape_is_blocked(),
    "processes-bounded": (
        cgroup_value("pids.max") == "64" and process_escape_is_blocked()
    ),
    "root-read-only": blocked(
        lambda: Path("/opt/rps/isolation-write").write_text("blocked")
    ),
    "seccomp-active": STATUS["Seccomp"] == "2",
    "shared-memory-read-only": blocked(
        lambda: Path("/dev/shm/isolation-write").write_text("blocked")
    ),
    "temporary-filesystem-bounded": (
        os.statvfs("/tmp").f_blocks * os.statvfs("/tmp").f_frsize
        <= 16_777_216
    ),
    "temporary-filesystem-overflow-blocked": (
        temporary_filesystem_overflow_is_blocked()
    ),
}
FAILED_CHECKS = sorted(name for name, passed in CHECKS.items() if not passed)
if FAILED_CHECKS:
    print("failed isolation checks: " + ", ".join(FAILED_CHECKS), file=sys.stderr)


def choose_move(turn, my_history, opponent_history, rng):
    return "R" if all(CHECKS.values()) else "P"
