from python_wrapper import run


def choose_move(turn, my_history, opponent_history, rng):
    return opponent_history[-1] if opponent_history else "R"


if __name__ == "__main__":
    run(choose_move)
