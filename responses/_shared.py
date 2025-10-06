# responses/_shared.py
from typing import Set


def tokenize(text: str) -> Set[str]:
    return {
        token.strip("!?.:,;()").lower()
        for token in text.split()
        if token.strip("!?.:,;()")
    }
