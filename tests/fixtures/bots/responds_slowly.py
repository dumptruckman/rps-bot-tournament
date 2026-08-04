import sys
import time


move = sys.argv[1]
response_delay_seconds = float(sys.argv[2])

for _ in range(3):
    sys.stdin.readline()
time.sleep(response_delay_seconds)
print(move, flush=True)
