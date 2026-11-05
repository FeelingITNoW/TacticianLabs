from collections import defaultdict

import numpy as np


SHOP_ODDS_PER_LEVEL = {
    2: {1: 1, 2: 0, 3: 0, 4: 0, 5: 0},
    3: {
        1: 0.75,
        2: 0.25,
        3: 0,
        4: 0,
        5: 0,
    },
    4: {1: 0.55, 2: 0.30, 3: 0.15, 4: 0, 5: 0},
    5: {1: 0.45, 2: 0.33, 3: 0.20, 4: 0.02, 5: 0},
    6: {1: 0.30, 2: 0.40, 3: 0.25, 4: 0.5, 5: 0},
    7: {1: 0.16, 2: 0.30, 3: 0.43, 4: 0.10, 5: 0.01},
    8: {1: 0.15, 2: 0.20, 3: 0.32, 4: 0.30, 5: 0.03},
    9: {1: 0.10, 2: 0.17, 3: 0.25, 4: 0.33, 5: 0.15},
    10: {1: 0.05, 2: 0.10, 3: 0.20, 4: 0.40, 5: 0.25},
    11: {1: 0.01, 2: 0.02, 3: 0.12, 4: 0.50, 5: 0.35},
}
POOL_SIZES_INDIVIDUAL = {1: 30, 2: 25, 3: 18, 4: 10, 5: 9}
POOL_SIZES_TOTAL = {1: 420, 2: 325, 3: 252, 4: 140, 5: 90}


def calculate_roll_odds_args_parser(args):
    level = args["level"]


# Calculating the odds of hitting a specific board state
def calculate_roll_odds():
    pass


# Generate the full transition matrix for the Markov Chain
def generate_transition_matrix(units_to_hit: dict):
    copies_to_hit = units_to_hit.values()
    row_col_states = generate_row_col_states(copies_to_hit)
    matrix_length = (len(row_col_states), len(row_col_states))
    transition_matrix = np.zeros(matrix_length)
    P_by_cost_and_copies = defaultdict(int)

    for m in range(matrix_length[0]):
        for n in range(matrix_length[1]):
            copies_bought = row_col_states

            transition_matrix[m][n] = 0


# Generate the row/col states for the transition matrix
def generate_row_col_states(copies_to_hit: list):
    list_of_states = []
    curr_state = [0] * len(copies_to_hit)
    curr_idx = 0
    while list_of_states != curr_state:
        list_of_states.append(curr_state)
        curr_state[curr_idx] += 1
        if curr_state[curr_idx] == copies_to_hit[curr_idx]:
            curr_idx += 1
    return list_of_states


# Calculate individual cells for the transition matrix of the Markov Chain
def cell_odds_calculation(
    level: int, target_unit_cost: int, copies_in_pool: int, same_cost_units_in_pool: int
):
    shop_odds_at_player_level = SHOP_ODDS_PER_LEVEL[level]
    P_hit_tier_in_shop = shop_odds_at_player_level[target_unit_cost]
    P_hit_unit_in_shop = copies_in_pool / same_cost_units_in_pool * P_hit_tier_in_shop

    return P_hit_unit_in_shop
