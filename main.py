import os
import json
import logging
import time
import random
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Optional

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

# --- ГУМАНИЗАТОР: НАБОРЫ ТЕКСТОВ ---

GREETINGS_HUGE = [
    "🔥 <b>ПОДЪЕХАЛА ГОДНОТА!</b>",
    "💸 <b>ЗАБИРАЙ, ПОКА БЕСПЛАТНО!</b>",
    "🎮 <b>100% СКИДКА! ТАКОЕ МЫ БЕРЕМ!</b>",
    "🚀 <b>СРОЧНЫЙ ДРОП! НАЛЕТАЙ!</b>",
    "🎁 <b>ПОДАРОЧЕК ДЛЯ ВАШЕЙ БИБЛИОТЕКИ!</b>",
    "✨ <b>НОВЫЙ ЛУТ В КОЛЛЕКЦИЮ!</b>",
    "💎 <b>АЛМАЗ НАЙДЕН! ЗАБИРАЕМ:</b>",
    "🚨 <b>АТЕНЬШН! ОЧЕРЕДНАЯ ХАЛЯВА:</b>"
]

GREETINGS_CASUAL = [
    "Привет, геймеры! Смотрите, что нашел:",
    "Опа, еще одна раздача подъехала!",
    "Не проходим мимо, сегодня раздают это:",
    "Всем доброго времени суток! Ловите свежий подгон:",
    "Если искали, во что поиграть — вот вариант за 0 рублей:"
]

SIGN_OFFS = [
    "Приятной игры! 🕹",
    "Увидимся в онлайне! ✌️",
    "Не забудь рассказать друзьям! 📢",
    "Жми на кнопку ниже, пока не закончилось! 👇",
    "Пополнил коллекцию? Ставь лайк! ❤️"
]

GENRE_EMOJIS = {
    "action": "🧨",
    "rpg": "🗡",
    "shooter": "🔫",
    "racing": "🏎",
    "strategy": "🧠",
    "indie": "🎨",
    "horror": "👻",
    "puzzle": "🧩",
    "adventure": "🗺",
    "default": "👾"
}

# --- ФУНКЦИИ ---

def load_posted_ids() -> List[str]:
    if os.path.exists(POSTED_IDS_FILE):
        try:
            with open(POSTED_IDS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
    return []

def save_posted_ids(ids: List[str]):
    with open(POSTED_IDS_FILE, 'w', encoding='utf-8') as f:
        json.dump(ids[-500:], f, indent=4)

def fetch_reddit_freebies() -> List[Dict]:
    """Парсинг сабреддита /r/FreeGameFindings через RSS"""
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
            # Извлекаем ID поста более надежно
            post_id = ""
            if id_tag:
                post_id = id_tag.text.split("/")[-1]
            if not post_id and link_tag:
                # Если нет ID, пытаемся вытащить его из URL сабреддита
                post_id = url.split("/comments/")[-1].split("/")[0]
            
            if not post_id:
                post_id = title.replace(" ", "_")[:50] # Последний шанс: ID из названия
            
            # Фильтрация
            if any(x.lower() in title.lower() for x in ["[Discussion]", "[PSA]", "Megathread", "Thread", "Ended", "Expired"]):
                continue
            
            direct_url = ""
            image_url = ""
            description = ""
            
            content_tag = entry.find("content")
            if content_tag:
                c_soup = BeautifulSoup(content_tag.text, "html.parser")
                # Ищем прямую ссылку
                for a in c_soup.find_all("a"):
                    if "[link]" in a.text:
                        direct_url = a.get("href")
                        break
                
                # Ищем картинку
                img = c_soup.find("img")
                if img:
                    image_url = img.get("src")
                
                # Пытаемся вытянуть хоть какой-то текст
                all_text = c_soup.get_text(separator=" ").strip()
                if len(all_text) > 20: 
                    # Обрезаем лишнее (обычно в Reddit RSS много тех. ссылок)
                    description = all_text.split("submitted by")[0].strip()[:200]

            games.append({
                "id": f"reddit_{post_id}",
                "title": title,
                "url": direct_url if direct_url else url,
                "image_url": image_url,
                "description": description,
                "source": "Reddit",
                "price": None
            })
    except Exception as e:
        logger.error(f"Ошибка Reddit RSS: {e}")
        
    return games

def fetch_epic_games_freebies() -> List[Dict]:
    """Парсинг официального API раздач Epic Games Store"""
    logger.info("Поиск в Epic Games...")
    url = "https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions?locale=ru&allowCountries=RU"
    games = []
    
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        elements = data.get("data", {}).get("Catalog", {}).get("searchStore", {}).get("elements", [])
        
        for el in elements:
            # Логика проверки раздачи
            promotions = el.get("promotions", {})
            if not promotions: continue
                
            offers = promotions.get("promotionalOffers", [])
            if not offers: continue
                
            active_offers = offers[0].get("promotionalOffers", [])
            is_active = False
            for offer in active_offers:
                if offer.get("startDate") and offer.get("endDate"):
                    is_active = True
                    break
            if not is_active: continue

            price_info = el.get("price", {}).get("totalPrice", {})
            if price_info.get("discountPrice", 0) != 0: continue # Не 100% скидка

            title = el.get("title", "")
            description = el.get("description", "")
            
            # Ссылка
            slug = el.get("productSlug") or el.get("urlSlug")
            if not slug and el.get("catalogNs", {}).get("mappings"):
                for m in el["catalogNs"]["mappings"]:
                    if m.get("pageType") == "productHome":
                        slug = m.get("pageSlug")
                        break
            if not slug: slug = title.lower().replace(" ", "-")
            game_url = f"https://store.epicgames.com/ru/p/{slug}"
            
            # Картинка
            image_url = ""
            priority_types = ["OfferImageWide", "DieselStoreFrontWide", "Thumbnail"]
            for p_type in priority_types:
                for img in el.get("keyImages", []):
                    if img.get("type") == p_type:
                        image_url = img.get("url")
                        break
                if image_url: break
            if not image_url and el.get("keyImages"): image_url = el["keyImages"][0].get("url")

            # Цена (для гуманизации)
            original_price = price_info.get("fmtPrice", {}).get("originalPrice", "0")
            
            games.append({
                "id": f"epic_{el.get('id')}",
                "title": f"[Epic Games] {title}",
                "url": game_url,
                "image_url": image_url,
                "description": description,
                "source": "EpicGames",
                "original_price": original_price
            })
            
    except Exception as e:
        logger.error(f"Ошибка Epic Games API: {e}")
        
    return games

def send_telegram_post(game: Dict) -> bool:
    """Оформление и отправка 'живого' поста"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning(f"[ТЕСТ] Пост: {game['title']}")
        return True
        
    # 1. Выбираем приветствие
    greeting = random.choice(GREETINGS_HUGE if random.random() > 0.4 else GREETINGS_CASUAL)
    
    # 2. Чистим заголовок и определяем платформу/жанр
    clean_title = game['title']
    platform_tag = ""
    dynamic_tags = ["#халява", "#бесплатно"]

    if "[Steam]" in clean_title: 
        platform_name = "🎮 <b>Steam</b>"
        platform_tag = "#Steam"
    elif "[Epic Games]" in clean_title or game['source'] == "EpicGames": 
        platform_name = "⬛️ <b>Epic Games</b>"
        platform_tag = "#EGS #EpicGames"
    elif "[GOG]" in clean_title: 
        platform_name = "🟣 <b>GOG</b>"
        platform_tag = "#GOG"
    elif "[Ubisoft]" in clean_title:
        platform_name = "🔵 <b>Ubisoft</b>"
        platform_tag = "#Ubisoft"
    else:
        platform_name = "👾 <b>PC</b>"

    if platform_tag:
        dynamic_tags.append(platform_tag)

    for tag in ["[Steam]", "[Epic Games]", "[GOG]", "[Ubisoft]", "[Origin]", "(Game)", "(DLC)", "[Itch.io]", "(Beta)"]:
        clean_title = clean_title.replace(tag, "").strip()
    
    emoji = GENRE_EMOJIS["default"]
    title_lower = clean_title.lower()
    if "race" in title_lower or "drive" in title_lower: 
        emoji = GENRE_EMOJIS["racing"]
        dynamic_tags.append("#гонки")
    elif "shot" in title_lower or "war" in title_lower or "gun" in title_lower: 
        emoji = GENRE_EMOJIS["shooter"]
        dynamic_tags.append("#шутер")
    elif "horror" in title_lower or "scary" in title_lower: 
        emoji = GENRE_EMOJIS["horror"]
        dynamic_tags.append("#хоррор")
    elif "rpg" in title_lower or "quest" in title_lower: 
        emoji = GENRE_EMOJIS["rpg"]
        dynamic_tags.append("#rpg")
    elif "strategy" in title_lower or "empire" in title_lower: 
        emoji = GENRE_EMOJIS["strategy"]
        dynamic_tags.append("#стратегия")
    
    # 3. Собираем текст
    text = f"{greeting}\n\n"
    text += f"{platform_name}\n"
    text += f"{emoji} <b>{clean_title}</b>\n\n"
    
    # Описание
    if game.get('description'):
        desc = game['description'].split('. ')[0]
        if len(desc) > 150: desc = desc[:147] + "..."
        text += f"<i>— {desc.strip()}</i>\n\n"
    
    # Цена
    if game.get('original_price') and game['original_price'] != "0":
        text += f"💰 Обычная цена: <s>{game['original_price']}</s> -> <b>БЕСПЛАТНО</b>\n\n"
    else:
        text += f"💰 Цена для тебя: <b>0 рублей</b>\n\n"
        
    text += f"🔗 <a href='{game['url']}'>ЗАБРАТЬ ПО ССЫЛКЕ</a>\n\n"
    
    # Прощалка
    text += f"{random.choice(SIGN_OFFS)}\n\n"
    text += " ".join(list(set(dynamic_tags))) # Удаляем дубликаты тегов
    
    # 5. Отправка
    payload = {"chat_id": TELEGRAM_CHAT_ID, "parse_mode": "HTML"}
    if game['image_url']:
        api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        payload.update({"photo": game['image_url'], "caption": text})
    else:
        api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload.update({"text": text, "disable_web_page_preview": False})

    try:
        response = requests.post(api_url, data=payload, timeout=12)
        response.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Ошибка Telegram: {e}")
        return False

def main():
    logger.info("Запуск бота поиска халявы...")
    posted_ids = load_posted_ids()
    
    reddit_games = fetch_reddit_freebies()
    epic_games = fetch_epic_games_freebies()
    all_new_games = reddit_games + epic_games
    
    to_post = [g for g in all_new_games if g["id"] not in posted_ids]
    if not to_post:
        logger.info("Новых раздач нет.")
        return

    # Берем самые свежие и ограничиваем лимит
    to_post = list(reversed(to_post))[:MAX_POSTS_PER_RUN]
    
    posted_count = 0
    for i, game in enumerate(to_post):
        if i > 0 and i % BATCH_SIZE == 0:
            logger.info(f"Пауза {BATCH_DELAY} сек...")
            time.sleep(BATCH_DELAY)

        if send_telegram_post(game):
            posted_ids.append(game["id"])
            save_posted_ids(posted_ids)
            posted_count += 1
            time.sleep(10) # Анти-спам внутри пачки
                
    if posted_count > 0:
        logger.info(f"Опубликовано: {posted_count}")

if __name__ == "__main__":
    main()
