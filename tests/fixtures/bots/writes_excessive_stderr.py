import sys


move = sys.argv[1]
stderr_bytes = int(sys.argv[2])

sys.stderr.write("x" * stderr_bytes)
sys.stderr.flush()
for _ in range(3):
    sys.stdin.readline()
print(move, flush=True)
