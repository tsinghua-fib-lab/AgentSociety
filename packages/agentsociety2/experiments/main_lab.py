"""Run a game with PersonAgent instead of a specialized game agent.

Example: python experiments/main_lab.py public_goods --games 1 --rounds 2 --agents 2
"""

from _games import main

if __name__ == "__main__":
    main(person_agent=True)
