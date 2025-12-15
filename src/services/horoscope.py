from datetime import date
from prometheus_client import Counter
from src.utils.logger import logger

# --- МЕТРИКИ ---
# Позволяет видеть в Графане, какие знаки зодиака самые популярные среди пользователей
ZODIAC_CALCULATION_TOTAL = Counter(
    'rex_zodiac_calculated_total', 
    'Total zodiac signs calculated', 
    ['sign']
)

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
    try:
        day = birth_date.day
        month = birth_date.month
        
        sign = "pisces" # Значение по умолчанию
        
        # Скорпион (10.23) - Стрелец (11.22)
        if (month == 3 and day >= 21) or (month == 4 and day <= 19): sign = "aries"
        elif (month == 4 and day >= 20) or (month == 5 and day <= 20): sign = "taurus"
        elif (month == 5 and day >= 21) or (month == 6 and day <= 20): sign = "gemini"
        elif (month == 6 and day >= 21) or (month == 7 and day <= 22): sign = "cancer"
        elif (month == 7 and day >= 23) or (month == 8 and day <= 22): sign = "leo"
        elif (month == 8 and day >= 23) or (month == 9 and day <= 22): sign = "virgo"
        elif (month == 9 and day >= 23) or (month == 10 and day <= 22): sign = "libra"
        elif (month == 10 and day >= 23) or (month == 11 and day <= 21): sign = "scorpio"
        elif (month == 11 and day >= 22) or (month == 12 and day <= 21): sign = "sagittarius"
        elif (month == 12 and day >= 22) or (month == 1 and day <= 19): sign = "capricorn"
        elif (month == 1 and day >= 20) or (month == 2 and day <= 18): sign = "aquarius"
        
        # Фиксируем метрику (бизнес-аналитика: кого у нас больше)
        ZODIAC_CALCULATION_TOTAL.labels(sign=sign).inc()
        
        return sign

    except Exception as e:
        # Логируем ошибку, если вдруг передали не дату
        logger.error("zodiac_calculation_failed", error=str(e), input_value=str(birth_date))
        # Возвращаем дефолт, чтобы не ронять бота, или рейзим ошибку дальше
        # В данном случае лучше вернуть ошибку наверх, чтобы юзер узнал, что дата кривая
        raise e