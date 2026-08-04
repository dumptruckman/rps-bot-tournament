from pathlib import Path
import sys
import time


own_marker = Path(sys.argv[1])
peer_marker = Path(sys.argv[2])
move = sys.argv[3]

for _ in range(3):
    sys.stdin.readline()
own_marker.touch()

deadline = time.monotonic() + 1
while not peer_marker.exists() and time.monotonic() < deadline:
    time.sleep(0.005)
print(move if peer_marker.exists() else "invalid", flush=True)
