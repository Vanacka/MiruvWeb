from datetime import date as date_type, timedelta


def _easter_sunday(year: int) -> date_type:
    """Anonymní gregoriánský algoritmus (computus) pro výpočet data Velikonoční neděle."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date_type(year, month, day)


def czech_state_holidays(year: int) -> dict[date_type, str]:
    """Státní svátky ČR pro daný rok (pevná data + pohyblivé svátky odvozené od Velikonoc)."""
    easter = _easter_sunday(year)
    return {
        date_type(year, 1, 1): "Den obnovy samostatného českého státu",
        easter - timedelta(days=2): "Velký pátek",
        easter + timedelta(days=1): "Velikonoční pondělí",
        date_type(year, 5, 1): "Svátek práce",
        date_type(year, 5, 8): "Den vítězství",
        date_type(year, 7, 5): "Den slovanských věrozvěstů Cyrila a Metoděje",
        date_type(year, 7, 6): "Den upálení mistra Jana Husa",
        date_type(year, 9, 28): "Den české státnosti",
        date_type(year, 10, 28): "Den vzniku samostatného československého státu",
        date_type(year, 11, 17): "Den boje za svobodu a demokracii",
        date_type(year, 12, 24): "Štědrý den",
        date_type(year, 12, 25): "1. svátek vánoční",
        date_type(year, 12, 26): "2. svátek vánoční",
    }


def is_czech_state_holiday(day: date_type) -> bool:
    return day in czech_state_holidays(day.year)


def czech_state_holiday_name(day: date_type) -> str | None:
    return czech_state_holidays(day.year).get(day)
