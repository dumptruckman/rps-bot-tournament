from python_wrapper import run


def choose_move(turn, my_history, opponent_history, rng):
    return rng.choice(("R", "P", "S"))


if __name__ == "__main__":
    run(choose_move)
