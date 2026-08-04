from pathlib import Path
import signal
import sys
import time


marker = Path(sys.argv[1])
response = sys.argv[2]


def mark_termination(*_ignored: object) -> None:
    marker.touch()
    raise SystemExit(0)


signal.signal(signal.SIGTERM, mark_termination)
for _ in range(3):
    sys.stdin.readline()
print(response, flush=True)
while True:
    time.sleep(1)
