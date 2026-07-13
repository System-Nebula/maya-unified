"""Edge predicate vocabulary for the AtomicNote graph."""

from enum import Enum


class Predicate(str, Enum):
    RELATED_TO = "related_to"
    REFINES = "refines"
    DERIVED_FROM = "derived_from"
    PRECEDED_BY = "preceded_by"
    OVERLAPS = "overlaps"
    MEETS = "meets"
    # Structural predicates: recipe -> ingredient / technique. Kept separate
    # from RELATED_TO so graph queries don't mix similarity with composition.
    CONTAINS = "contains"
    EMPLOYS = "employs"
