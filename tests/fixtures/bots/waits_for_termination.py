from pathlib import Path
import sys
import time


marker = Path(sys.argv[1])
move = sys.argv[2]
wait_seconds = float(sys.argv[3])

for _ in range(3):
    sys.stdin.readline()

deadline = time.monotonic() + wait_seconds
while not marker.exists() and time.monotonic() < deadline:
    time.sleep(0.005)
print(move if marker.exists() else "invalid", flush=True)
