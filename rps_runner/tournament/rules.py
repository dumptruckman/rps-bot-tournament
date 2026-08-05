"""Canonical accepted Tournament rules sealed in every Manifest."""

from __future__ import annotations

from typing import Any


def manifest_rules() -> dict[str, Any]:
    """Return a fresh JSON-compatible representation of the accepted rules."""

    return {
        "scoring": {
            "series": {
                "maximum_matches": 3,
                "match_wins_to_end_early": 2,
                "series_points": {
                    "match_win": {"numerator": 1, "denominator": 1},
                    "match_draw": {"numerator": 1, "denominator": 2},
                    "double_forfeit": {"numerator": 0, "denominator": 1},
                },
                "winner": "most_series_points",
                "qualifying_tie": "series_draw",
                "playoff_tie": "higher_qualifying_seed_advances",
            },
            "qualifying_standing_points": {
                "series_win": 3,
                "series_draw": 1,
                "series_loss": 0,
            },
            "protocol_fault_forfeit": {
                "opponent_receives_match_win": True,
                "opponent_receives_series_point": True,
                "retain_completed_rounds_only": True,
                "counts_in_match_differential": True,
                "counts_in_protocol_fault_forfeits": True,
                "synthesize_unplayed_rounds": False,
            },
            "double_forfeit": {
                "winner": None,
                "series_points_each": {"numerator": 0, "denominator": 1},
                "consumes_match_ordinal": True,
                "retain_completed_rounds_only": True,
            },
            "administrative_series_win": {
                "standing_points": 3,
                "series_wins": 1,
                "match_statistics": False,
                "round_statistics": False,
                "fault_statistics": False,
            },
        },
        "tie_breaks": {
            "phase": "qualifying",
            "criteria": [
                {"field": "standing_points", "direction": "descending"},
                {"field": "series_wins", "direction": "descending"},
                {
                    "field": "head_to_head_series_result",
                    "direction": "winner_first",
                    "applies_when": "exactly_two_teams_remain_tied",
                },
                {
                    "field": "match_differential",
                    "direction": "descending",
                    "definition": "match_wins_minus_match_losses",
                },
                {
                    "field": "round_differential",
                    "direction": "descending",
                    "definition": "round_wins_minus_round_losses",
                },
                {
                    "field": "protocol_fault_forfeits",
                    "direction": "ascending",
                },
                {"field": "tie_break_key", "direction": "ascending"},
            ],
            "disqualified_team_series": {
                "preserve_played_records": True,
                "exclude_match_statistics": True,
                "exclude_round_statistics": True,
                "exclude_timing_statistics": True,
                "exclude_fault_statistics": True,
            },
            "administrative_series_wins_excluded_from_lower_statistics": True,
        },
        "disqualification": {
            "cause": "confirmed_security_violation",
            "scope": "entire_tournament",
            "rejected_attribution": "infrastructure_failure",
            "qualifying": {
                "eligible_opponents_receive_administrative_series_win": True,
                "skip_future_fixtures": True,
                "preserve_played_records": True,
                "exclude_affected_lower_tie_break_statistics": True,
            },
            "before_bracket_lock": {
                "remove_disqualified_team": True,
                "reselect_playoff_field": True,
                "reseed_playoff_field": True,
            },
            "after_bracket_lock": {
                "allow_new_qualifying_team": False,
                "reseed": False,
                "current_series_opponent_receives_administrative_win": True,
                (
                    "reinstate_most_recently_eliminated_team_when_next_"
                    "series_not_started"
                ): True,
                "after_final_starts_remaining_finalist_is_champion": True,
            },
        },
        "playoffs": {
            "field_selection": "highest_ranked_eligible_teams",
            "maximum_field_size": 4,
            "bracket_lock": "start_of_first_playoff_match",
            "formats": {
                "four_or_more_eligible": {
                    "semifinals": [[1, 4], [2, 3]],
                    "semifinal_winners_play_final": True,
                },
                "three_eligible": {
                    "seed_one_advances_to_final": True,
                    "semifinal": [2, 3],
                },
                "two_eligible": {"direct_final": [1, 2]},
                "one_eligible": {
                    "declare_tournament_champion": True,
                    "play_matches": False,
                },
                "no_eligible": {"abort_without_champion": True},
            },
        },
    }
