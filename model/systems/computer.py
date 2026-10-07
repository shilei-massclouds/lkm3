"""Computer System"""

from dataclasses import dataclass

from framework.engine import System


@dataclass
class Computer(System):
    def __repr__(self):
        return "Computer"
