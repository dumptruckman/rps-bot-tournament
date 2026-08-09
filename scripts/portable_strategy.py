def choose_move(turn, my_history, opponent_history, rng):
    return ("R", "P", "S")[turn % 3]
