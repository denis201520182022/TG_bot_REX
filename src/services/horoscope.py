from datetime import date

ZODIAC_SIGNS = {
    "aries": (3, 21), "taurus": (4, 20), "gemini": (5, 21), "cancer": (6, 21),
    "leo": (7, 23), "virgo": (8, 23), "libra": (9, 23), "scorpio": (10, 23),
    "sagittarius": (11, 22), "capricorn": (12, 22), "aquarius": (1, 20), "pisces": (2, 19)
}

RUS_SIGNS = {
    "aries": "Овен", "taurus": "Телец", "gemini": "Близнецы", "cancer": "Рак",
    "leo": "Лев", "virgo": "Дева", "libra": "Весы", "scorpio": "Скорпион",
    "sagittarius": "Стрелец", "capricorn": "Козерог", "aquarius": "Водолей", "pisces": "Рыбы"
}

def get_zodiac_sign(birth_date: date) -> str:
    """Вычисляет знак зодиака (на латинице) по дате"""
    # Трюк: сравниваем (месяц, день)
    # Если дата меньше границы знака, значит это предыдущий знак. 
    # Но проще перебором, их всего 12.
    day = birth_date.day
    month = birth_date.month
    
    # Скорпион (10.23) - Стрелец (11.22)
    # Простой алгоритм:
    if (month == 3 and day >= 21) or (month == 4 and day <= 19): return "aries"
    if (month == 4 and day >= 20) or (month == 5 and day <= 20): return "taurus"
    if (month == 5 and day >= 21) or (month == 6 and day <= 20): return "gemini"
    if (month == 6 and day >= 21) or (month == 7 and day <= 22): return "cancer"
    if (month == 7 and day >= 23) or (month == 8 and day <= 22): return "leo"
    if (month == 8 and day >= 23) or (month == 9 and day <= 22): return "virgo"
    if (month == 9 and day >= 23) or (month == 10 and day <= 22): return "libra"
    if (month == 10 and day >= 23) or (month == 11 and day <= 21): return "scorpio"
    if (month == 11 and day >= 22) or (month == 12 and day <= 21): return "sagittarius"
    if (month == 12 and day >= 22) or (month == 1 and day <= 19): return "capricorn"
    if (month == 1 and day >= 20) or (month == 2 and day <= 18): return "aquarius"
    return "pisces"