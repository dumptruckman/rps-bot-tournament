import sys


for move in sys.argv[1]:
    for _ in range(3):
        sys.stdin.readline()
    print(move, flush=True)
