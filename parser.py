import asyncio
import logging
import json
import os
from datetime import datetime
from dotenv import load_dotenv
from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup

load_dotenv()
HH_PROXY = os.getenv('HH_PROXY')

SEARCH_URL = "https://hh.ru/search/vacancy"

HEADERS = {
    "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 (jeeitunes@gmail.com)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://hh.ru/",
}

EXPERIENCE_MAP = {
    "noExperience": "Без опыта",
    "between1And3": "От 1 года до 3 лет",
    "between3And6": "От 3 до 6 лет",
    "moreThan6": "Более 6 лет"
}

WORK_FORMAT_MAP = {
    "REMOTE": "Удаленная работа",
    "HYBRID": "Гибридный формат",
    "ON_SITE": "В офисе",
    "FIELD_WORK": "Разъездная работа"
}

def format_salary(comp: dict) -> str:
    """Форматирует блок зарплаты из JSON hh.ru"""
    if not comp or 'noCompensation' in comp:
        return "Не указана"
    
    fr = comp.get('from')
    to = comp.get('to')
    curr = comp.get('currencyCode', 'RUB')
    gross_text = " до вычета налогов" if comp.get('gross') else " на руки"
    
    if fr and to:
        return f"от {fr} до {to} {curr}{gross_text}"
    elif fr:
        return f"от {fr} {curr}{gross_text}"
    elif to:
        return f"до {to} {curr}{gross_text}"
    return "Не указана"

def format_date(iso_date_str: str) -> str:
    """Форматирует ISO дату в читаемый вид: ДД.ММ.ГГГГ ЧЧ:ММ"""
    if not iso_date_str:
        return "Не указана"
    try:
        # Парсим строку вида '2026-04-21T12:17:50.647+03:00'
        dt = datetime.fromisoformat(iso_date_str)
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return iso_date_str

async def fetch_vacancies() -> list:
    params = {
        "education": "not_required_or_not_specified",
        "ored_clusters": "true",
        "text": "Data scientist",
        "order_by": "publication_time"
    }

    proxy_config = {"http": HH_PROXY, "https": HH_PROXY} if HH_PROXY else None

    async with AsyncSession(impersonate="chrome124", timeout=15, proxies=proxy_config) as session:
        try:
            response = await session.get(SEARCH_URL, headers=HEADERS, params=params)

            if response.status_code != 200:
                logging.error(f"❌ Ошибка загрузки страницы: {response.status_code}")
                return[]

            soup = BeautifulSoup(response.text, 'html.parser')
            state_template = soup.find('template', id='HH-Lux-InitialState')
            
            if not state_template:
                logging.error("❌ Не найден тег состояния HH-Lux-InitialState. Возможно hh.ru изменил вёрстку.")
                return[]

            state_json = json.loads(state_template.text)
            raw_vacancies = state_json.get('vacancySearchResult', {}).get('vacancies', [])
            
            unique_vacancies =[]
            seen_ids = set()

            for vac in raw_vacancies:
                vac_id = str(vac.get('vacancyId'))
                if not vac_id or vac_id in seen_ids:
                    continue
                
                # ФИЛЬТРАЦИЯ ПО ОПЫТУ
                exp_code = vac.get('workExperience', '')
                if exp_code not in ('noExperience', 'between1And3'):
                    continue 

                # Вытаскиваем форматы работы
                raw_formats = vac.get('workFormats', [])
                formats_list =[]
                if raw_formats and len(raw_formats) > 0:
                    elements = raw_formats[0].get('workFormatsElement', [])
                    formats_list =[WORK_FORMAT_MAP.get(f, f) for f in elements]

                company_info = vac.get('company', {})
                pub_time_raw = vac.get('publicationTime', {}).get('$', '')

                # Формируем итоговый словарь со всеми новыми крутыми данными
                processed_vac = {
                    'id': vac_id,
                    'name': vac.get('name', 'Без названия'),
                    'url': f"https://hh.ru/vacancy/{vac_id}",
                    'employer': company_info.get('name', 'Неизвестная компания'),
                    'salary': format_salary(vac.get('compensation', {})),
                    'experience': EXPERIENCE_MAP.get(exp_code, exp_code),
                    'area': vac.get('area', {}).get('name', 'Локация не указана'),
                    'work_formats': ", ".join(formats_list) if formats_list else "Не указан",
                    
                    # НОВЫЕ ПОЛЯ
                    'published_at': format_date(pub_time_raw),
                    'responses': vac.get('totalResponsesCount', 0),
                    'viewers_now': vac.get('online_users_count', 0),
                    'is_it_accredited': company_info.get('accreditedITEmployer', False),
                    'accept_temporary': vac.get('acceptTemporary', False),
                    'rating': company_info.get('employerReviews', {}).get('totalRating', None)
                }
                
                seen_ids.add(vac_id)
                unique_vacancies.append(processed_vac)

            logging.info(f"📥 Найдено {len(unique_vacancies)} подходящих вакансий.")
            return unique_vacancies

        except Exception as e:
            logging.error(f"💥 Ошибка парсера: {e}", exc_info=True)
            return[]