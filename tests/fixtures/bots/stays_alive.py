import os
from pathlib import Path
import sys
import time


pid_file = Path(sys.argv[1])
move = sys.argv[2]

pid_file.write_text(str(os.getpid()))
for _ in range(3):
    sys.stdin.readline()
print(move, flush=True)
while True:
    time.sleep(1)
