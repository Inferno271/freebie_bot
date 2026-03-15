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

TAGS = "#халява #бесплатно #free"
GREETINGS = [
    "🔥 Горячая раздача!",
    "💸 Забирай, пока бесплатно!",
    "🎮 100% скидка подъехала!",
    "🚀 Срочно на аккаунт!"
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
    """Парсинг сабреддита /r/FreeGameFindings"""
    logger.info("Поиск на Reddit...")
    url = "https://www.reddit.com/r/FreeGameFindings/new.json?limit=15"
    headers = {"User-Agent": "python:freebie_telegram_bot:v1.0 (by u/No_Name)"}
    games = []
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        children = data.get("data", {}).get("children", [])
        
        for child in children:
            post = child.get("data", {})
            title = post.get("title", "")
            
            # Строгая фильтрация от мусора
            if any(x.lower() in title.lower() for x in ["[Discussion]", "[PSA]", "Megathread", "Thread", "Ended"]):
                continue
                
            image_url = ""
            preview = post.get("preview", {})
            if preview and preview.get("images"):
                try:
                    image_url = preview["images"][0]["source"]["url"].replace("&amp;", "&")
                except (KeyError, IndexError):
                    pass
                    
            games.append({
                "id": f"reddit_{post.get('id')}",
                "title": title,
                "url": post.get("url", ""),
                "image_url": image_url,
                "source": "Reddit"
            })
    except Exception as e:
        logger.error(f"Ошибка Reddit API: {e}")
        
    return games

def fetch_epic_games_freebies() -> List[Dict]:
    """Парсинг официального API раздач Epic Games Store"""
    logger.info("Поиск в Epic Games...")
    url = "https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions?locale=ru&country=RU&allowCountries=RU"
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
            # Ищем лучшую горизонтальную обложку
            for img in key_images:
                if img.get("type") in ["OfferImageWide", "DieselStoreFrontWide"]:
                    image_url = img.get("url")
                    break
            
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
    
    posted_count = 0
    # Идем с конца для правильного хронологического порядка
    for game in reversed(all_new_games):
        if game["id"] not in posted_ids:
            logger.info(f"Новая раздача найдена: {game['title']}")
            if send_telegram_post(game):
                posted_ids.append(game["id"])
                save_posted_ids(posted_ids)
                posted_count += 1
                time.sleep(3) # Anti-Spam пауза
                
    if posted_count == 0:
        logger.info("Новых раздач пока нет.")

if __name__ == "__main__":
    main()
