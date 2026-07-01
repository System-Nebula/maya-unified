"""
ELO Calculation Service
=======================
Glicko-2 rating system for Arena battles.

Standard ELO with K-factor of 32.
"""

import math
from dataclasses import dataclass
from typing import Optional


@dataclass
class ELOResult:
    """Result of ELO calculation."""

    winner_new_rating: int
    loser_new_rating: int
    winner_change: int
    loser_change: int


class ELOCalculator:
    """ELO rating calculator using standard formula."""

    K_FACTOR = 32  # Standard K-factor
    INITIAL_RATING = 1200

    @staticmethod
    def expected_score(rating_a: int, rating_b: int) -> float:
        """Calculate expected score for player A."""
        return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400))

    @staticmethod
    def calculate(
        winner_rating: int,
        loser_rating: int,
        draw: bool = False,
        k_factor: int | None = None,
    ) -> ELOResult:
        """
        Calculate new ratings after a battle.

        Args:
            winner_rating: Current rating of the winner
            loser_rating: Current rating of the loser
            draw: Whether the result was a draw
            k_factor: K-factor (default: 32)

        Returns:
            ELOResult with new ratings and changes
        """
        k = k_factor or ELOCalculator.K_FACTOR

        expected_winner = ELOCalculator.expected_score(winner_rating, loser_rating)
        expected_loser = ELOCalculator.expected_score(loser_rating, winner_rating)

        if draw:
            actual_winner = 0.5
            actual_loser = 0.5
        else:
            actual_winner = 1.0
            actual_loser = 0.0

        winner_change = int(k * (actual_winner - expected_winner))
        loser_change = int(k * (actual_loser - expected_loser))

        new_winner = max(100, winner_rating + winner_change)
        new_loser = max(100, loser_rating + loser_change)

        return ELOResult(
            winner_new_rating=new_winner,
            loser_new_rating=new_loser,
            winner_change=winner_change,
            loser_change=loser_change,
        )

    @staticmethod
    def calculate_from_battle(
        candidate_a_rating: int,
        candidate_b_rating: int,
        winner_id: Optional[str],
        is_tie: bool = False,
    ) -> tuple[tuple[int, int], tuple[int, int]]:
        """
        Calculate ratings for both candidates based on battle outcome.

        Returns:
            tuple of ((a_new_rating, a_change), (b_new_rating, b_change))
        """
        if is_tie:
            result = ELOCalculator.calculate(
                candidate_a_rating, candidate_b_rating, draw=True
            )
            return (
                (result.winner_new_rating, result.winner_change),
                (result.loser_new_rating, result.loser_change),
            )

        if winner_id == "a":
            result = ELOCalculator.calculate(
                candidate_a_rating, candidate_b_rating, draw=False
            )
            return (
                (result.winner_new_rating, result.winner_change),
                (result.loser_new_rating, result.loser_change),
            )
        else:
            result = ELOCalculator.calculate(
                candidate_b_rating, candidate_a_rating, draw=False
            )
            return (
                (result.loser_new_rating, result.loser_change),
                (result.winner_new_rating, result.winner_change),
            )


class Glicko2Calculator:
    """
    Glicko-2 rating system (more sophisticated than ELO).

    Not implemented yet — reserved for future use.
    """

    DEFAULT_RD = 350
    MIN_RD = 50
    TAU = 0.5

    @staticmethod
    def calculate_new_rating(
        rating: float,
        rd: float,
        opponent_rating: float,
        opponent_rd: float,
        score: float,
    ) -> tuple[float, float]:
        """Calculate new Glicko-2 rating and RD."""
        raise NotImplementedError("Glicko-2 not yet implemented")


def update_ratings(
    winner_rating: int,
    loser_rating: int,
) -> tuple[int, int, int, int]:
    """Update ratings and return (new_winner, new_loser, winner_change, loser_change)."""
    result = ELOCalculator.calculate(winner_rating, loser_rating)
    return (
        result.winner_new_rating,
        result.loser_new_rating,
        result.winner_change,
        result.loser_change,
    )


def get_expected_probability(rating_a: int, rating_b: int) -> float:
    """Get probability that A wins against B."""
    return ELOCalculator.expected_score(rating_a, rating_b)
