import logging
import json
import os
import urllib.parse
from datetime import datetime
from dotenv import load_dotenv
from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

load_dotenv()
HH_PROXY = os.getenv('HH_PROXY')

SEARCH_URL = "https://hh.ru/search/vacancy"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 (jeeitunes@gmail.com)",
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
    if not iso_date_str:
        return "Не указана"
    try:
        dt = datetime.fromisoformat(iso_date_str)
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return iso_date_str

def extract_vacancies(html_content: str) -> tuple[list, str]:
    """
    Парсит HTML и возвращает кортеж: (список_вакансий, статус_парсинга)
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Проверка на капчу
    page_title = soup.title.text.strip() if soup.title else ""
    if "Ой!" in page_title or "защит" in page_title.lower() or "Cloudflare" in page_title:
        return[], "captcha"

    state_template = soup.find('template', id='HH-Lux-InitialState')
    if not state_template:
        return[], "no_template"

    try:
        state_json = json.loads(state_template.text)
    except json.JSONDecodeError:
        return[], "json_error"

    raw_vacancies = state_json.get('vacancySearchResult', {}).get('vacancies',[])
    
    if not raw_vacancies:
        return[], "empty_json"
        
    unique_vacancies =[]
    seen_ids = set()

    for vac in raw_vacancies:
        vac_id = str(vac.get('vacancyId'))
        if not vac_id or vac_id in seen_ids:
            continue
        
        # Фильтрация по опыту
        exp_code = vac.get('workExperience', '')
        if exp_code not in ('noExperience', 'between1And3'):
            continue 

        raw_formats = vac.get('workFormats',[])
        formats_list =[]
        if raw_formats and len(raw_formats) > 0:
            elements = raw_formats[0].get('workFormatsElement', [])
            formats_list =[WORK_FORMAT_MAP.get(f, f) for f in elements]

        company_info = vac.get('company', {})
        pub_time_raw = vac.get('publicationTime', {}).get('$', '')

        processed_vac = {
            'id': vac_id,
            'name': vac.get('name', 'Без названия'),
            'url': f"https://hh.ru/vacancy/{vac_id}",
            'employer': company_info.get('name', 'Неизвестная компания'),
            'salary': format_salary(vac.get('compensation', {})),
            'experience': EXPERIENCE_MAP.get(exp_code, exp_code),
            'area': vac.get('area', {}).get('name', 'Локация не указана'),
            'work_formats': ", ".join(formats_list) if formats_list else "Не указан",
            'published_at': format_date(pub_time_raw),
            'responses': vac.get('totalResponsesCount', 0),
            'viewers_now': vac.get('online_users_count', 0),
            'is_it_accredited': company_info.get('accreditedITEmployer', False),
            'accept_temporary': vac.get('acceptTemporary', False),
            'rating': company_info.get('employerReviews', {}).get('totalRating', None)
        }
        
        seen_ids.add(vac_id)
        unique_vacancies.append(processed_vac)

    return unique_vacancies, "success"

async def fetch_html_with_browser(url: str) -> str:
    logging.info("🌐 Запускаем браузер-симулятор (Сhromium)...")
    
    async with async_playwright() as p:
        proxy_config = {"server": HH_PROXY} if HH_PROXY else None
        
        try:
            browser = await p.chromium.launch(
                headless=True, 
                proxy=proxy_config,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
            )
            
            # Создаем контекст с эмуляцией обычного Chrome на Windows
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="ru-RU"
            )
            
            # 🔥 ВАЖНО: Устанавливаем куку региона, чтобы HH не путался
            await context.add_cookies([{
                'name': 'hhtoken',
                'value': 'invalid', # просто заглушка
                'domain': '.hh.ru',
                'path': '/'
            }, {
                'name': 'area',
                'value': '113', # Москва (как базовый регион для поиска)
                'domain': '.hh.ru',
                'path': '/'
            }])

            page = await context.new_page()
            
            # Переходим по URL
            logging.info(f"🔗 Переход по адресу...")
            await page.goto(url, wait_until="networkidle", timeout=60000)
            
            # Даем время на прогрузку динамики
            await page.wait_for_timeout(7000)

            # ДИАГНОСТИКА
            # Проверяем, нет ли на странице текста "ничего не найдено" или капчи
            content = await page.content()
            if "вакансий не найдено" in content.lower() or "ничего не найдено" in content.lower():
                logging.warning('🕵️ На странице написано: "Ничего не найдено". Сохраняю скриншот для проверки.')
                await page.screenshot(path="debug_empty_search.png")
            
            if "капча" in content.lower() or "робот" in content.lower():
                logging.warning("🚨 Вероятнее всего мы наткнулись на капчу. Делаю скриншот.")
                await page.screenshot(path="debug_captcha.png")

            html = await page.content()
            return html
            
        except Exception as e:
            logging.error(f"❌ Ошибка в симуляторе браузера: {e}")
            return ""
        finally:
            if 'browser' in locals():
                await browser.close()


async def fetch_vacancies() -> list:
    params = {
        "text": "Data scientist",
        "area": "113", 
        "education": "not_required_or_not_specified",
        "ored_clusters": "true",
        "order_by": "publication_time"
    }

    # Формируем полный URL для браузера
    query_string = urllib.parse.urlencode(params)
    full_url = f"{SEARCH_URL}?{query_string}"

    proxy_config = {"http": HH_PROXY, "https": HH_PROXY} if HH_PROXY else None
    
    # ПОПЫТКА 1: Быстрый запрос через curl_cffi
    logging.info("🚀 Запрос через curl_cffi...")
    
    html_content = ""
    async with AsyncSession(impersonate="chrome124", timeout=15, proxies=proxy_config) as session:
        try:
            response = await session.get(SEARCH_URL, headers=HEADERS, params=params)
            if response.status_code == 200:
                html_content = response.text
            else:
                logging.warning(f"⚠️ Ошибка curl_cffi (код {response.status_code}).")
        except Exception as e:
            logging.error(f"💥 Ошибка соединения curl_cffi: {e}")

    # Проверяем результат первой попытки
    if html_content:
        vacancies, status = extract_vacancies(html_content)
        if status == "success" and len(vacancies) > 0:
            logging.info(f"✅ Успешно собрано {len(vacancies)} вакансий через curl_cffi.")
            return vacancies
        else:
            logging.warning(f"⚠️ Страница загружена успешно, но список вакансий пуст. (статус: {status}).")

    # ПОПЫТКА 2: Симуляция браузера через Playwright
    # Мы доходим сюда только если curl_cffi поймал капчу или вернул пустую страницу
    html_content = await fetch_html_with_browser(full_url)
    
    if not html_content:
        logging.error("❌ Не удалось получить HTML даже через симулятор браузера.")
        return []

    vacancies, status = extract_vacancies(html_content)
    
    if status == "success":
        logging.info(f"✅ Успешно собрано {len(vacancies)} вакансий через Сhromium.")
        return vacancies
    else:
        logging.error(f"❌ Попытка парсинга через Сhromium провалена. Статус: {status}")
        return []