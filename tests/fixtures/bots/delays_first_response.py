import sys
import time


moves = sys.argv[1]
first_response_delay_seconds = float(sys.argv[2])

for turn, move in enumerate(moves):
    for _ in range(3):
        sys.stdin.readline()
    if turn == 0:
        time.sleep(first_response_delay_seconds)
    print(move, flush=True)
