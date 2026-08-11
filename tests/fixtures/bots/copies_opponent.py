import sys


while True:
    turn = sys.stdin.readline()
    if turn == "":
        break
    my_history = sys.stdin.readline()
    opponent_history = sys.stdin.readline()
    if my_history == "" or opponent_history == "":
        break
    history = opponent_history.rstrip("\n")
    print(history[-1] if history != "-" else "R", flush=True)
