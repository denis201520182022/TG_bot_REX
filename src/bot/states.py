from aiogram.fsm.state import StatesGroup, State

class SurveyState(StatesGroup):
    in_progress = State() # Пользователь внутри анкеты (неважно какой)
    final_consent = State()