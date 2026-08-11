#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time


STATE = Path(os.environ["FAKE_DOCKER_STATE"])
LOG = STATE / "calls.jsonl"


def log(command: str, **details: object) -> None:
    record = json.dumps(
        {"command": command, "wall_time_ns": time.time_ns(), **details},
        sort_keys=True,
    )
    descriptor = os.open(LOG, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, (record + "\n").encode("utf-8"))
    finally:
        os.close(descriptor)


def create(arguments: list[str]) -> int:
    image = arguments[-1]
    log("create", image=image, arguments=arguments)
    if image == "create-failure":
        print("simulated create failure", file=sys.stderr)
        return 19
    container_id = arguments[arguments.index("--name") + 1]
    environment = {}
    labels = {}
    for index, argument in enumerate(arguments):
        if argument == "--env":
            key, value = arguments[index + 1].split("=", 1)
            environment[key] = value
        if argument == "--label":
            key, value = arguments[index + 1].split("=", 1)
            labels[key] = value
    (STATE / container_id).write_text(
        json.dumps(
            {"image": image, "environment": environment, "labels": labels}
        )
    )
    if image == "malformed-create":
        print("bad\ncontainer-id")
        return 0
    if image == "timeout-create":
        time.sleep(1)
    print(container_id)
    return 0


def wait_for_peer_start() -> None:
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if sum(
            json.loads(line)["command"] == "start"
            for line in LOG.read_text().splitlines()
        ) >= 2:
            return
        time.sleep(0.005)


def play(image: str) -> int:
    if image == "early-exit":
        return 0
    if image == "missing-readiness":
        sys.stdin.buffer.read()
        return 0
    if image == "early-stdout":
        sys.stdout.write("R\n")
        sys.stdout.flush()
    if image.startswith("barrier-"):
        wait_for_peer_start()
    if image == "diagnostic-r":
        sys.stderr.write("before\nRPS_")
        sys.stderr.flush()
        time.sleep(0.01)
        sys.stderr.write("READY_V1\nafter\n")
    elif image == "repeated-marker-r":
        sys.stderr.write("RPS_READY_V1\nRPS_READY_V1\n")
    elif image == "unterminated-diagnostic-r":
        sys.stderr.write("x" * 100_000 + "\nRPS_READY_V1\n")
    elif image == "escaped-import-r":
        sys.stderr.write(
            "RPS_STDERR_ESCAPE_V1:RPS_READY_V1\nRPS_READY_V1\n"
        )
    else:
        sys.stderr.write("RPS_READY_V1\n")
    sys.stderr.flush()

    if image in {
        "oom-r",
        "pid-exhaustion-r",
        "open-file-exhaustion-r",
        "filesystem-exhaustion-r",
        "security-evidence-r",
        "denied-operation-r",
        "inspect-failure-r",
        "host-exhaustion-r",
    }:
        return 137 if image in {"oom-r", "disconnect-oom-r"} else 1

    if image == "disconnect-oom-r":
        os.close(0)
        time.sleep(1)
        return 137

    move = "S" if image.endswith("-s") else "R"
    while True:
        turn = sys.stdin.buffer.readline()
        if not turn:
            if image == "final-diagnostic-r":
                sys.stderr.write("final diagnostic\n")
                sys.stderr.flush()
            if image == "final-overflow-r":
                sys.stderr.write("x" * 100_000)
                sys.stderr.flush()
            return 0
        if not sys.stdin.buffer.readline() or not sys.stdin.buffer.readline():
            return 0
        if image == "slow-r":
            time.sleep(0.1)
        response = (
            "X"
            if image == "invalid-r"
            else "R" * 100
            if image == "overflow-r"
            else move
        )
        sys.stdout.write(response + "\n")
        sys.stdout.flush()


def start(arguments: list[str]) -> int:
    container_id = arguments[-1]
    details = json.loads((STATE / container_id).read_text())
    log("start", container_id=container_id, image=details["image"])
    if details["image"] == "attach-failure":
        print("simulated attach failure", file=sys.stderr)
        return 125
    return play(details["image"])


def inspect(arguments: list[str]) -> int:
    container_id = arguments[-1]
    details = json.loads((STATE / container_id).read_text())
    image = details["image"]
    if image == "inspect-failure-r":
        print("simulated inspect failure", file=sys.stderr)
        return 33
    status = "created" if image == "attach-failure" else "exited"
    log("inspect", container_id=container_id, status=status)
    errors = {
        "pid-exhaustion-r": "RPS_RESOURCE_EVIDENCE_V1:pid_exhaustion",
        "open-file-exhaustion-r": (
            "RPS_RESOURCE_EVIDENCE_V1:open_file_exhaustion"
        ),
        "filesystem-exhaustion-r": (
            "RPS_RESOURCE_EVIDENCE_V1:filesystem_exhaustion"
        ),
        "security-evidence-r": (
            "RPS_SECURITY_EVIDENCE_V1:runtime-monitor-incident-42"
        ),
        "denied-operation-r": "runtime: operation not permitted",
        "host-exhaustion-r": "runtime: no space left on host device",
    }
    print(
        json.dumps(
            {
                "Status": status,
                "ExitCode": 137
                if image in {"oom-r", "disconnect-oom-r"}
                else 1,
                "OOMKilled": image in {"oom-r", "disconnect-oom-r"},
                "Error": errors.get(image, ""),
            }
        )
    )
    return 0


def list_containers(arguments: list[str]) -> int:
    requested_labels = [
        arguments[index + 1].removeprefix("label=")
        for index, argument in enumerate(arguments)
        if argument == "--filter"
    ]
    log("ps", arguments=arguments)
    for path in STATE.iterdir():
        if path.name == "calls.jsonl" or path.name.startswith(".control-"):
            continue
        details = json.loads(path.read_text())
        labels = details.get("labels", {})
        if all(
            labels.get(key) == value
            for key, value in (
                requested_label.split("=", 1)
                for requested_label in requested_labels
            )
        ):
            print(path.name)
    return 0


def lifecycle(command: str, arguments: list[str]) -> int:
    container_id = arguments[-1]
    log(command, container_id=container_id)
    container_path = STATE / container_id
    if command == "stop":
        details = json.loads(container_path.read_text())
        if details["image"] == "stubborn-s":
            time.sleep(1)
    if command == "rm":
        details = (
            json.loads(container_path.read_text())
            if container_path.exists()
            else {}
        )
        if str(details.get("image", "")).startswith("remove-failure-"):
            print("simulated remove failure", file=sys.stderr)
            return 31
        container_path.unlink(missing_ok=True)
    return 0


def main() -> int:
    STATE.mkdir(parents=True, exist_ok=True)
    command, arguments = sys.argv[1], sys.argv[2:]
    if command == "create":
        return create(arguments)
    if command == "start":
        return start(arguments)
    if command == "inspect":
        return inspect(arguments)
    if command == "ps":
        return list_containers(arguments)
    if command == "version":
        log("version", arguments=arguments)
        if (STATE / ".control-version-failure").exists():
            print("daemon unavailable", file=sys.stderr)
            return 34
        print(json.dumps({"Version": "fake-1", "Os": "linux", "Arch": "amd64"}))
        return 0
    if command in {"stop", "kill", "rm"}:
        return lifecycle(command, arguments)
    print("unsupported fake Docker command: " + command, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
