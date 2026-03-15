import os
import json
import logging
import time
import requests
from bs4 import BeautifulSoup
from typing import List, Dict

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("FreebieBot")

# Конфигурация
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
POSTED_IDS_FILE = "posted_ids.json"

# Настройки пауз и лимитов (чтобы не спамить всё сразу)
MAX_POSTS_PER_RUN = 6    # Максимум постов за один запуск (раз в час)
BATCH_SIZE = 2           # Сколько постов слать подряд
BATCH_DELAY = 600        # Пауза между пачками постов (в секундах, например 600 = 10 мин)

TAGS = "#халява #бесплатно #free #игры"
GREETINGS = [
    "🔥 <b>ПОДЪЕХАЛА ГОДНОТА!</b>",
    "💸 <b>ЗАБИРАЙ, ПОКА БЕСПЛАТНО!</b>",
    "🎮 <b>100% СКИДКА! ТАКОЕ МЫ БЕРЕМ!</b>",
    "🚀 <b>СРОЧНЫЙ ДРОП! НАЛЕТАЙ!</b>",
    "🎁 <b>ПОДАРОЧЕК ДЛЯ ВАШЕЙ БИБЛИОТЕКИ!</b>",
    "✨ <b>НОВЫЙ ЛУТ В КОЛЛЕКЦИЮ!</b>"
]

def load_posted_ids() -> List[str]:
    if os.path.exists(POSTED_IDS_FILE):
        try:
            with open(POSTED_IDS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
    return []

def save_posted_ids(ids: List[str]):
    # Оставляем только последние 500 ID, чтобы файл не разрастался
    with open(POSTED_IDS_FILE, 'w', encoding='utf-8') as f:
        json.dump(ids[-500:], f, indent=4)

def fetch_reddit_freebies() -> List[Dict]:
    """Парсинг сабреддита /r/FreeGameFindings через RSS (более стабильно для ботов)"""
    logger.info("Поиск на Reddit...")
    url = "https://www.reddit.com/r/FreeGameFindings/new/.rss"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    }
    games = []
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, features="xml")
        entries = soup.find_all("entry")
        
        for entry in entries:
            title = entry.find("title").text if entry.find("title") else ""
            link_tag = entry.find("link")
            url = link_tag.get("href") if link_tag else ""
            id_tag = entry.find("id")
            post_id = id_tag.text.split("/")[-1] if id_tag else str(time.time())
            
            # Фильтрация
            if any(x.lower() in title.lower() for x in ["[Discussion]", "[PSA]", "Megathread", "Thread", "Ended", "Expired"]):
                continue
            
            # В RSS ссылка в теге <link> ведет на Reddit. 
            # Нам нужна ПРЯМАЯ ссылка на магазин/сайт.
            # Она обычно запрятана в <content> внутри тега <a> с текстом [link]
            direct_url = ""
            content = entry.find("content").text if entry.find("content") else ""
            if content:
                c_soup = BeautifulSoup(content, "html.parser")
                # Ищем ссылку, которая содержит текст [link]
                for a in c_soup.find_all("a"):
                    if "[link]" in a.text:
                        direct_url = a.get("href")
                        break
                
                # Поиск картинки (если есть)
                img = c_soup.find("img")
                if img:
                    image_url = img.get("src")

            # Если не нашли прямую ссылку, берем ссылку на пост в Reddit
            final_url = direct_url if direct_url else url

            games.append({
                "id": f"reddit_{post_id}",
                "title": title,
                "url": final_url,
                "image_url": image_url,
                "source": "Reddit"
            })
    except Exception as e:
        logger.error(f"Ошибка Reddit RSS: {e}")
        
    return games

def fetch_epic_games_freebies() -> List[Dict]:
    """Парсинг официального API раздач Epic Games Store"""
    logger.info("Поиск в Epic Games...")
    # Убираем жесткую привязку к RU, чтобы избежать пустых ответов из-за региональных ограничений GitHub
    url = "https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions?locale=ru&allowCountries=RU"
    games = []
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        elements = data.get("data", {}).get("Catalog", {}).get("searchStore", {}).get("elements", [])
        
        for el in elements:
            promotions = el.get("promotions", {})
            if not promotions:
                continue
                
            offers = promotions.get("promotionalOffers", [])
            if not offers:
                continue
                
            active_offers = offers[0].get("promotionalOffers", [])
            is_active = False
            for offer in active_offers:
                start_date = offer.get("startDate")
                end_date = offer.get("endDate")
                if start_date and end_date:
                    is_active = True
                    break
                    
            if not is_active:
                continue

            price_info = el.get("price", {}).get("totalPrice", {})
            discount = price_info.get("discount", 0)
            original_price = price_info.get("originalPrice", 1)
            
            if discount < original_price and price_info.get("discountPrice", 0) != 0:
                 continue

            title = el.get("title", "")
            product_slug = el.get("productSlug")
            url_slug = el.get("urlSlug")
            
            # EGS иногда меняет логику генерации URL
            slug = product_slug if product_slug else url_slug
            if not slug and el.get("catalogNs", {}).get("mappings"):
                mappings = el["catalogNs"]["mappings"]
                for mapping in mappings:
                    if mapping.get("pageType") == "productHome":
                        slug = mapping.get("pageSlug")
                        break
                        
            if not slug:
                # Фоллбэк, если вообще нет слага
                slug = title.lower().replace(" ", "-")
                
            game_url = f"https://store.epicgames.com/ru/p/{slug}"
            
            image_url = ""
            key_images = el.get("keyImages", [])
            # Ищем самый качественное изображение
            priority_types = ["OfferImageWide", "DieselStoreFrontWide", "Thumbnail", "CodeRedemptionImages"]
            for p_type in priority_types:
                for img in key_images:
                    if img.get("type") == p_type:
                        image_url = img.get("url")
                        break
                if image_url: break
            
            if not image_url and key_images:
                 image_url = key_images[0].get("url", "")
                 
            game_id = f"epic_{el.get('id')}"
            
            games.append({
                "id": game_id,
                "title": f"[Epic Games] {title}",
                "url": game_url,
                "image_url": image_url,
                "source": "EpicGames"
            })
            
    except Exception as e:
        logger.error(f"Ошибка Epic Games API: {e}")
        
    return games

def send_telegram_post(game: Dict) -> bool:
    """Оформление и отправка поста"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning(f"[ТЕСТОВЫЙ ЗАПУСК - ТОКЕНЫ НЕ ЗАДАНЫ] Пост: {game['title']} | {game['url']}")
        return True
        
    import random
    greeting = random.choice(GREETINGS)
    
    # Очистка названия от тегов
    clean_title = game['title']
    platform = ""
    
    if "[Steam]" in clean_title: platform = "🎮 <b>Steam</b>"
    elif "[Epic Games]" in clean_title: platform = "⬛️ <b>Epic Games</b>"
    elif "[GOG]" in clean_title: platform = "🟣 <b>GOG</b>"
    elif "[Ubisoft]" in clean_title: platform = "🔵 <b>Ubisoft</b>"
    
    # Удаляем все теги в квадратных и круглых скобках для красоты
    for tag in ["[Steam]", "[Epic Games]", "[GOG]", "[Ubisoft]", "[Origin]", "(Game)", "(DLC)", "(Other)", "[Itch.io]", "(Beta)"]:
        clean_title = clean_title.replace(tag, "").strip()
        
    # Формируем итоговое сообщение (HTML)
    text = f"{greeting}\n\n"
    if platform:
        text += f"{platform}\n"
    text += f"🎁 <b>{clean_title}</b>\n\n"
    text += f"🔗 <a href='{game['url']}'>Забрать халяву</a>\n\n"
    text += f"{TAGS}"
    
    if game['image_url']:
        api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "photo": game['image_url'],
            "caption": text,
            "parse_mode": "HTML",
        }
    else:
        api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }

    try:
        response = requests.post(api_url, data=payload, timeout=10)
        response.raise_for_status()
        logger.info(f"Успешный пост: {game['title']}")
        return True
    except Exception as e:
        logger.error(f"Ошибка отправки в TG: {e}")
        return False

def main():
    logger.info("Запуск бота поиска халявы...")
    posted_ids = load_posted_ids()
    
    reddit_games = fetch_reddit_freebies()
    epic_games = fetch_epic_games_freebies()
    
    all_new_games = reddit_games + epic_games
    
    # Оставляем только те, что еще не постили
    to_post = [g for g in all_new_games if g["id"] not in posted_ids]
    
    if not to_post:
        logger.info("Новых раздач пока нет.")
        return

    # Ограничиваем количество постов за один запуск
    to_post = list(reversed(to_post))[:MAX_POSTS_PER_RUN]
    
    posted_count = 0
    for i, game in enumerate(to_post):
        # Логика задержки (пауза после каждых BATCH_SIZE постов)
        if i > 0 and i % BATCH_SIZE == 0:
            logger.info(f"Пауза {BATCH_DELAY} секунд между пачками постов...")
            time.sleep(BATCH_DELAY)

        logger.info(f"Публикация: {game['title']}")
        if send_telegram_post(game):
            posted_ids.append(game["id"])
            save_posted_ids(posted_ids)
            posted_count += 1
            # Короткая пауза внутри пачки
            time.sleep(5)
                
    if posted_count > 0:
        logger.info(f"Успешно опубликовано раздач в этом запуске: {posted_count}")

if __name__ == "__main__":
    main()
