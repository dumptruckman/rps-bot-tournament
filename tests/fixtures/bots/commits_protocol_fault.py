import sys


fault_kind = sys.argv[1]

for _ in range(3):
    sys.stdin.readline()

if fault_kind == "invalid_utf8":
    sys.stdout.buffer.write(b"\xff\n")
    sys.stdout.buffer.flush()
elif fault_kind == "multiple_responses":
    sys.stdout.write("R\nP\n")
    sys.stdout.flush()
elif fault_kind == "excessive_output":
    sys.stdout.write("R" * 100_000)
    sys.stdout.flush()
elif fault_kind == "exits_early":
    raise SystemExit(0)
else:
    raise ValueError(f"Unknown protocol fault fixture: {fault_kind}")
