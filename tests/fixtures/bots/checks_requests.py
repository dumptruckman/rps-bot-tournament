import sys


moves = sys.argv[1]
opponent_moves = sys.argv[2]

for turn, move in enumerate(moves):
    actual_request = [
        sys.stdin.readline().rstrip("\n") for _ in range(3)
    ]
    expected_request = [
        str(turn),
        moves[:turn] or "-",
        opponent_moves[:turn] or "-",
    ]
    print(move if actual_request == expected_request else "invalid", flush=True)
