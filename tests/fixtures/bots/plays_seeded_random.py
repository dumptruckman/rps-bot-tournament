import os
import random
import sys


rng = random.Random(int(os.environ["RPS_SEED"]))
while True:
    turn = sys.stdin.readline()
    if turn == "":
        break
    my_history = sys.stdin.readline()
    opponent_history = sys.stdin.readline()
    if my_history == "" or opponent_history == "":
        break
    print(rng.choice(("R", "P", "S")), flush=True)
