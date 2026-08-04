import os
import sys


moves = sys.argv[1]
expected_protocol_version = sys.argv[2]
expected_rounds = sys.argv[3]
expected_seed = sys.argv[4]
expected_environment = (
    expected_protocol_version,
    expected_rounds,
    expected_seed,
)
actual_environment = (
    os.environ["RPS_PROTOCOL_VERSION"],
    os.environ["RPS_ROUNDS"],
    os.environ["RPS_SEED"],
)

for turn, move in enumerate(moves):
    request = [sys.stdin.readline().rstrip("\n") for _ in range(3)]
    if actual_environment != expected_environment or request[0] != str(turn):
        print("invalid", flush=True)
    else:
        print(move, flush=True)
