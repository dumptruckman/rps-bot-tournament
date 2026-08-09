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
        {"command": command, "time_ns": time.monotonic_ns(), **details},
        sort_keys=True,
    )
    descriptor = os.open(LOG, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, (record + "\n").encode("utf-8"))
    finally:
        os.close(descriptor)


def create(arguments: list[str]) -> int:
    image = arguments[-1]
    log("create", image=image)
    if image == "create-failure":
        print("simulated create failure", file=sys.stderr)
        return 19
    container_id = arguments[arguments.index("--name") + 1]
    environment = {}
    for index, argument in enumerate(arguments):
        if argument == "--env":
            key, value = arguments[index + 1].split("=", 1)
            environment[key] = value
    (STATE / container_id).write_text(
        json.dumps({"image": image, "environment": environment})
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

    move = "S" if image.endswith("-s") else "R"
    while True:
        turn = sys.stdin.buffer.readline()
        if not turn:
            if image == "final-diagnostic-r":
                sys.stderr.write("final diagnostic\n")
                sys.stderr.flush()
            return 0
        if not sys.stdin.buffer.readline() or not sys.stdin.buffer.readline():
            return 0
        sys.stdout.write(move + "\n")
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
    status = "created" if details["image"] == "attach-failure" else "exited"
    log("inspect", container_id=container_id, status=status)
    print(status)
    return 0


def lifecycle(command: str, arguments: list[str]) -> int:
    container_id = arguments[-1]
    log(command, container_id=container_id)
    if command == "rm":
        (STATE / container_id).unlink(missing_ok=True)
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
    if command in {"stop", "kill", "rm"}:
        return lifecycle(command, arguments)
    print("unsupported fake Docker command: " + command, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
