from __future__ import annotations

import os
import random
import sys
import tempfile

READY_MARKER = "RPS_READY_V1"
IMPORT_STDERR_ESCAPE = b"RPS_STDERR_ESCAPE_V1:"
INFRASTRUCTURE_ENVIRONMENT = {
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "TZ": "UTC",
    "HOME": "/tmp",
    "TMPDIR": "/tmp",
}
PROTOCOL_ENVIRONMENT = (
    "RPS_PROTOCOL_VERSION",
    "RPS_ROUNDS",
    "RPS_SEED",
)


def sanitize_environment() -> str:
    """Re-exec with only the profile's bot-visible environment."""

    if len(sys.argv) == 3 and sys.argv[1] == "--environment-sanitized":
        visible_environment = dict(INFRASTRUCTURE_ENVIRONMENT)
        for name in PROTOCOL_ENVIRONMENT:
            visible_environment[name] = os.environ[name]
        os.environ.clear()
        os.environ.update(visible_environment)
        return sys.argv[2]
    team_directory = os.getcwd()
    environment = dict(INFRASTRUCTURE_ENVIRONMENT)
    for name in PROTOCOL_ENVIRONMENT:
        environment[name] = os.environ[name]
    os.execve(
        sys.executable,
        [
            sys.executable,
            "-I",
            os.path.abspath(__file__),
            "--environment-sanitized",
            team_directory,
        ],
        environment,
    )
    raise AssertionError("os.execve returned")


def read_history(line: str) -> str:
    return "" if line == "-" else line


def load_strategy():
    saved_stderr = os.dup(2)
    diagnostics = tempfile.TemporaryFile()
    try:
        os.dup2(diagnostics.fileno(), 2)
        try:
            from strategy import choose_move

            sys.stderr.flush()
        finally:
            os.dup2(saved_stderr, 2)
            os.close(saved_stderr)
        diagnostics.seek(0)
        return choose_move, diagnostics
    except BaseException:
        diagnostics.close()
        raise


def write_stderr(content: bytes) -> None:
    while content:
        written = os.write(2, content)
        content = content[written:]


def replay_import_stderr(diagnostics) -> None:
    marker = READY_MARKER.encode("ascii")
    pending = bytearray()
    ordinary_line = False
    while True:
        chunk = diagnostics.read(8192)
        if not chunk:
            break
        for value in chunk:
            byte = bytes((value,))
            if ordinary_line:
                write_stderr(byte)
                if byte == b"\n":
                    ordinary_line = False
                continue
            pending.append(value)
            candidate = bytes(pending)
            if candidate == IMPORT_STDERR_ESCAPE:
                write_stderr(IMPORT_STDERR_ESCAPE + candidate)
                pending.clear()
                ordinary_line = True
            elif byte == b"\n":
                line = bytes(pending[:-1])
                if line == marker:
                    write_stderr(IMPORT_STDERR_ESCAPE)
                write_stderr(bytes(pending))
                pending.clear()
            elif not marker.startswith(candidate) and not IMPORT_STDERR_ESCAPE.startswith(
                candidate
            ):
                write_stderr(candidate)
                pending.clear()
                ordinary_line = True
    if pending:
        write_stderr(bytes(pending))


def main() -> None:
    sys.path.insert(0, sanitize_environment())
    choose_move, import_diagnostics = load_strategy()
    rng = random.Random(int(os.environ["RPS_SEED"]))
    try:
        replay_import_stderr(import_diagnostics)
    finally:
        import_diagnostics.close()
    write_stderr(READY_MARKER.encode("ascii") + b"\n")
    while True:
        turn_line = sys.stdin.readline()
        if turn_line == "":
            return
        own_history_line = sys.stdin.readline()
        opponent_history_line = sys.stdin.readline()
        if own_history_line == "" or opponent_history_line == "":
            return
        move = choose_move(
            int(turn_line.rstrip("\n")),
            read_history(own_history_line.rstrip("\n")),
            read_history(opponent_history_line.rstrip("\n")),
            rng,
        )
        print(move, flush=True)


if __name__ == "__main__":
    main()
