import random
import re
from datetime import datetime, timedelta


def expand_spintax(text: str) -> str:
    pattern = re.compile(r"\{([^{}]+)\}")

    def replace(match: re.Match[str]) -> str:
        return random.choice(match.group(1).split("|"))

    while pattern.search(text):
        text = pattern.sub(replace, text)
    return text


def random_delay(min_sec: int, max_sec: int) -> float:
    return random.uniform(min_sec, max_sec)


def jitter_datetime(base: datetime, min_sec: int, max_sec: int) -> datetime:
    return base + timedelta(seconds=random.randint(min_sec, max_sec))


def country_from_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("7"):
        return "RU"
    if digits.startswith("380"):
        return "UA"
    if digits.startswith("375"):
        return "BY"
    if digits.startswith("77"):
        return "KZ"
    return "RU"
