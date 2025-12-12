import json
from gspread_asyncio import AsyncioGspreadClientManager
from google.oauth2.service_account import Credentials
from src.config import settings

def get_creds():
    creds = Credentials.from_service_account_file(settings.GOOGLE_CREDENTIALS_FILE)
    scoped = creds.with_scopes([
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ])
    return scoped

agcm = AsyncioGspreadClientManager(get_creds)

async def fetch_all_data():
    """Скачивает и вопросы (Лист 1), и промпты (Лист 2)"""
    agc = await agcm.authorize()
    sh = await agc.open_by_key(settings.GOOGLE_SHEET_ID)
    
    # 1. Читаем вопросы (Лист 1)
    ws_questions = await sh.get_worksheet(0)
    rows_q = await ws_questions.get_all_values()
    surveys = {}
    
    if rows_q:
        for r in rows_q[1:]:
            if len(r) < 4 or not r[0]: continue
            mode, key, q_type, text = r[0].strip(), r[1].strip(), r[2].strip(), r[3].strip()
            options = [x.strip() for x in r[4].split(',')] if len(r) > 4 and r[4] else []
            
            if mode not in surveys: surveys[mode] = []
            surveys[mode].append({"key": key, "type": q_type, "text": text, "options": options})

    # 2. Читаем промпты (Лист 2)
    # Пытаемся найти лист по имени "Prompts", если нет - берем второй по счету
    try:
        ws_prompts = await sh.worksheet("Prompts")
    except:
        try:
            ws_prompts = await sh.get_worksheet(1)
        except:
            ws_prompts = None

    prompts = {}
    if ws_prompts:
        rows_p = await ws_prompts.get_all_values()
        if rows_p:
            for r in rows_p[1:]: # Пропускаем заголовок
                if len(r) < 2 or not r[0]: continue
                mode, text = r[0].strip(), r[1].strip()
                prompts[mode] = text

    return surveys, prompts