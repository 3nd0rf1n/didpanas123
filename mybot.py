import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, ContextTypes,
    ConversationHandler, MessageHandler, filters,
    CallbackQueryHandler
)
from pymongo import MongoClient
from datetime import datetime, timedelta
import random
import asyncio
from telegram.constants import ParseMode
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from telegram.error import RetryAfter, TelegramError
import re
import os
from telegram.helpers import escape_markdown


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mongo_url = os.getenv("MONGO_URL", "mongodb://localhost:27017") 
client = MongoClient(mongo_url)
db = client["didpanas"]
users = db["panas_users"]

BET = 0
SLOTS_BET = 1
MULTIPLAYER_BET = 2


def calculate_level(games_played):
    if games_played < 10:
        return 1
    elif games_played < 30:
        return 2
    elif games_played < 60:
        return 3
    elif games_played < 100:
        return 4
    else:
        return 5

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username

    user = users.find_one({"user_id": user_id})
    welcome_text = (
        "👋 *Вітаємо, любий гравцю!*\n\n"
        "🎉 Ласкаво просимо до спільноти *«Дід Панас»* — місця, де азарт зустрічається з веселощами!\n\n"
        "💻 *Офіційний сайт:* [didpanas.netlify.app](https://didpanas.netlify.app)\n\n"
        "───────────────\n"
        "🕹️ *Команди для гри:*\n"
        "▫️ /coin — пограти в монетку (ставка від *10* до *1000* монет)\n"
        "▫️ /slots — пограти в слоти\n"
        "▫️ /balance — перевірити свій баланс\n"
        "▫️ /daily — отримати щоденний бонус\n"
        "▫️ /profile — переглянути свій профіль і досягнення\n"
        "▫️ /shop — магазин фіч для профілю\n\n"
        "▫️ /pay — передати свої грошики\n"
        "───────────────\n"
        "_Прокидай удачу, грай чесно і збирай виграші!_\n"
        "💰 *Бажаємо великих призів!* 🍀"
    )

    if not user:
        users.insert_one({
            "user_id": user_id,
            "username": username,
            "balance": 100,
            "last_daily": None,
            "wins": 0,
            "losses": 0,
            "games_played": 0,
            "win_streak": 0,
            "max_win_streak": 0,
            "total_winnings": 0,
            "level": 1,
            "achievements": [],
            "purchased_features": []
        })
        await update.message.reply_markdown(welcome_text)
    else:
        await update.message.reply_markdown("👋 Знову радий тебе бачити!\n\n" + welcome_text)

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users.find_one({"user_id": user_id})

    if user:
        await update.message.reply_text(
            f"💰 На твоєму рахунку зараз {user['balance']} монет.\n"
            "Готуйся робити ставки та вигравати!"
        )
    else:
        await update.message.reply_text(
            "⚠️ Виглядає, що ти ще не зареєстрований у нашій системі.\n\n"
            "Щоб почати гру і отримати доступ до всіх функцій, будь ласка, введи команду /start.\n"
            "Це займе лише кілька секунд, і тоді ти зможеш грати та вигравати монети! 🍀")

    keyboard = []
    for item in shop_items_vip:
        keyboard.append([InlineKeyboardButton(f"{item['name']} — {item['price']} монет", callback_data=f"buy_{item['id']}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🛒 Магазин фіч для профілю. Виберіть, що хочете придбати:", reply_markup=reply_markup)

async def buy_feature(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = users.find_one({"user_id": user_id})
    if not user:
        await query.edit_message_text("❌ Ви не зареєстровані. Напишіть /start")
        return

    feature_id = query.data.replace("buy_", "")
    item = next((i for i in shop_items_vip if i["id"] == feature_id), None)
    if not item:
        await query.edit_message_text("❌ Товар не знайдено.")
        return

    purchased = user.get("purchased_features", [])

    if feature_id in purchased:
        await query.edit_message_text("✅ Ви вже купили цю фічу.")
        return

    if user["balance"] < item["price"]:
        await query.edit_message_text("❌ Недостатньо монет для покупки.")
        return

    users.update_one(
        {"user_id": user_id},
        {
            "$inc": {"balance": -item["price"]},
            "$push": {"purchased_features": feature_id}
        }
    )
    await query.edit_message_text(f"🎉 Ви успішно купили: {item['name']}")

async def coin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users.find_one({"user_id": user_id})

    if not user:
        await update.message.reply_text(
            "⚠️ Виглядає, що ти ще не зареєстрований у нашій системі.\n\n"
            "Щоб почати гру і отримати доступ до всіх функцій, будь ласка, введи команду /start.\n"
            "Це займе лише кілька секунд, і тоді ти зможеш грати та вигравати монети! 🍀")
        return ConversationHandler.END

    await update.message.reply_text(
        f"🪙 Ласкаво просимо до гри 'Орел чи Решка'!\n\n"
        f"💰 У твоєму гаманці зараз: {user['balance']} монет.\n"
        "🎲 Введи суму ставки (тільки ціле число), і ми кинемо монету за тебе.\n\n"
        "Будь готовий — удача може бути на твоєму боці або ж обернутися проти!\n"
        "Готовий ризикнути і побачити результат? Введи суму, і хай щастить!\n\n"
        "⏹ Якщо хочеш скасувати гру — просто введи /cancel."
    )
    return BET

async def coin_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users.find_one({"user_id": user_id})
    text = update.message.text

    if not text.isdigit():
        await update.message.reply_text(
            "❌ Упс! Введи, будь ласка, **коректне ціле число** для ставки.\n"
            "Наприклад: 50 або 100."
        )
        return BET

    bet = int(text)

    if bet < 10:
        await update.message.reply_text(
            "⚠️ Ставка занадто мала! Мінімальна ставка — **10 монет**.\n"
            "Спробуй ввести трохи більшу суму, щоб отримати шанс на виграш!"
        )
        return BET

    if bet > 1000:
        await update.message.reply_text(
            "⚠️ Ого, це забагато! Максимальна ставка — **1000 монет**.\n"
            "Не варто ризикувати забагато за один раз 😉"
        )
        return BET

    if bet > user["balance"]:
        await update.message.reply_text(
            f"❌ У тебе немає стільки монет для ставки.\n"
            f"Твій баланс: {user['balance']} монет.\n"
            "Будь ласка, введи ставку, яку ти можеш дозволити собі."
        )
        return BET

    await asyncio.sleep(1)

    gif_path = "coin-flip.gif"
    animation_msg = await update.message.reply_animation(animation=open(gif_path, "rb"))
    await asyncio.sleep(3)
    await animation_msg.delete()

    result = random.choice(["win", "lose"])

    bonus_chance = random.random()
    bonus_text = ""
    if result == "win" and bonus_chance < 0.05:
        winnings = bet * 3
        bonus_text = "\n🔥 Бонус! Виграш потрійний!"
    elif result == "win":
        winnings = bet
    else:
        winnings = -bet

    new_balance = user["balance"] + winnings
    new_games_played = user.get("games_played", 0) + 1
    new_total_winnings = user.get("total_winnings", 0) + (winnings if winnings > 0 else 0)

    if result == "win":
        new_win_streak = user.get("win_streak", 0) + 1
    else:
        new_win_streak = 0

    new_max_win_streak = max(user.get("max_win_streak", 0), new_win_streak)

    new_level = calculate_level(new_games_played)

    achievements = user.get("achievements", [])

    def add_achievement(name):
        if name not in achievements:
            achievements.append(name)

    if new_win_streak >= 10:
        add_achievement("🏆 Переможець 10 ігор поспіль!")
    if new_total_winnings >= 1000:
        add_achievement("💰 Виграв 1000 монет!")
    if new_games_played >= 50:
        add_achievement("🎮 Зіграв 50 ігор!")

    update_fields = {
        "balance": new_balance,
        "wins": user.get("wins", 0) + (1 if result == "win" else 0),
        "losses": user.get("losses", 0) + (1 if result == "lose" else 0),
        "games_played": new_games_played,
        "win_streak": new_win_streak,
        "max_win_streak": new_max_win_streak,
        "total_winnings": new_total_winnings,
        "level": new_level,
        "achievements": achievements
    }

    users.update_one({"user_id": user_id}, {"$set": update_fields})

    msg = (
        f"{'🎉 Ура! Ти виграв ставку' if result == 'win' else '💀 На жаль, ти програв ставку'} {abs(winnings)} монет!"
        f"{bonus_text}\n\n"
        f"💰 Тепер твій баланс: {new_balance} монет\n"
        f"📊 Статистика: {update_fields['wins']} виграшів, {update_fields['losses']} програшів\n"
        f"🎲 Ігор зіграно: {new_games_played}\n"
        f"🔥 Рекордна серія виграшів: {new_max_win_streak}\n"
        f"⭐ Рівень: {new_level}\n"
    )

    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    return ConversationHandler.END

SLOT_SYMBOLS = ["🍒", "🍋", "🍉", "⭐", "🔔", "💎"]

async def safe_edit_message(message, text, delay=1.0):
    try:
        await message.edit_text(text)
        await asyncio.sleep(delay)
    except RetryAfter as e:
        print(f"[FLOOD] Telegram просить подождати {e.retry_after} сек.")
        await asyncio.sleep(e.retry_after)
        try:
            await message.edit_text(text)
        except Exception as ex:
            print(f"[ERROR after retry] {ex}")
    except TelegramError as e:
        print(f"[TelegramError] {e}")
    except Exception as e:
        print(f"[Other Error] {e}")

def rocket_progress(progress_percent: int) -> str:
    total_steps = 10
    filled_steps = int((progress_percent / 100) * total_steps)
    if filled_steps > total_steps:
        filled_steps = total_steps
    rocket_bar = "🚀" + "=" * filled_steps + ">" + " " * (total_steps - filled_steps)
    return f"{rocket_bar} ({progress_percent}%)"

async def slots_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users.find_one({"user_id": user_id})

    if user is None:
        await update.message.reply_text(
            "❌ Користувач не знайдений у базі.\n"
            "Будь ласка, зареєструйтесь за допомогою команди /start."
        )
        return ConversationHandler.END

    text = update.message.text

    if not text.isdigit():
        keyboard = [
            [InlineKeyboardButton("🤝 Зіграти з кимось", callback_data="multiplayer_slot")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"🎩 Ласкаво просимо до слот-зали!\n\n"
            f"💼 Ваш поточний баланс: {user['balance']} монет.\n"
            "💡 Введіть суму ставки (ціле число).\n\n"
            "🎰 Символи на барабанах:\n"
            "🍒 Вишні — класика\n"
            "🍋 Лимони — кисло, але вигідно\n"
            "🍉 Кавуни — шанс на великий виграш\n"
            "⭐ Зірки — символ удачі\n"
            "🔔 Дзвони — час виграшів\n"
            "💎 Діаманти — шлях до джекпоту!\n\n"
            "🎯 Введіть ставку і обертайте барабани.\n"
            "⏹ Щоб скасувати гру, введіть /cancel.",
            reply_markup=reply_markup
        )
        return SLOTS_BET

    bet = int(text)

    if bet < 10:
        await update.message.reply_text("❌ Мінімальна ставка — 10 монет. Будь ласка, спробуйте ще раз.")
        return SLOTS_BET
    if bet > user["balance"]:
        await update.message.reply_text("❌ Недостатньо монет для ставки. Будь ласка, зменшіть ставку.")
        return SLOTS_BET

    message = await update.message.reply_text("🎰 Обертаємо барабани...")

    spins = 5
    for i in range(spins):
        current_spin = [random.choice(SLOT_SYMBOLS) for _ in range(3)]
        display = " | ".join(current_spin)
        progress = int((i + 1) / spins * 100)
        rocket_bar = rocket_progress(progress)

        await safe_edit_message(
            message,
            f"🎰 Обертаємо барабани...\n\n"
            f"{display}\n\n"
            f"{rocket_bar}\n"
            f"💨 Крутилка в дії!"
        )

    if len(set(current_spin)) == 1:
        winnings = bet * 5
        win = 1
        lose = 0
        result_icon = "🎉🎉🎉"
        result_text = f"Вау! Три однакові символи — Джекпот! Ви виграли {winnings} монет!"
    elif len(set(current_spin)) == 2:
        winnings = bet * 2
        win = 1
        lose = 0
        result_icon = "✨"
        result_text = f"Чудово! Два однакових символи. Ви виграли {winnings} монет!"
    else:
        winnings = -bet
        win = 0
        lose = 1
        result_icon = "💔"
        result_text = f"На жаль, ви програли {bet} монет. Спробуйте ще раз!"

    new_balance = user["balance"] + winnings
    new_games_played = user.get("games_played", 0) + 1
    new_level = calculate_level(new_games_played)

    users.update_one(
        {"user_id": user_id},
        {"$set": {
            "balance": new_balance,
            "games_played": new_games_played,
            "wins": user.get("wins", 0) + win,
            "losses": user.get("losses", 0) + lose,
            "level": new_level
        }}
    )

    final_msg = (
        f"{result_icon} {result_text} {result_icon}\n\n"
        f"💰 Ваш новий баланс: *{new_balance}* монет\n"
        f"📊 Статистика: *{user.get('wins', 0) + win}* виграшів, *{user.get('losses', 0) + lose}* програшів\n"
        f"🎲 Ігор зіграно: *{new_games_played}*\n"
        f"⭐ Поточний рівень: *{new_level}*"
    )

    await safe_edit_message(message, final_msg, delay=0.1)

    return ConversationHandler.END

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users.find_one({"user_id": user_id})

    if not user:
        await update.message.reply_text("❌ Ви не зареєстровані. Напишіть /start")
        return

    now = datetime.utcnow()
    last = user.get("last_daily")

    if last and now - last < timedelta(hours=24):
        hours_left = 24 - (now - last).seconds // 3600
        await update.message.reply_text(f"⏳ Ще рано! Спробуй через {hours_left} год.")
    else:
        users.update_one(
            {"user_id": user_id},
            {"$set": {"balance": user["balance"] + 50, "last_daily": now}}
        )
        await update.message.reply_text("🎁 Ти отримав щоденний бонус 50 монет!")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛑 Гру скасовано. Не сумуй — завжди можна спробувати ще раз! 🎲"
    )
    return ConversationHandler.END

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users.find_one({"user_id": user_id})
    if not user:
        await update.message.reply_text("❌ Ви не зареєстровані. Напишіть /start")
        return

    backgrounds = [
        "1.jpg",
        "2.jpg",
        "3.jpg",
        "4.jpg",
        "illustration-anime-city.jpg"
    ]

    background_path = random.choice(backgrounds)
    background = Image.open(background_path).convert("RGBA")

    draw = ImageDraw.Draw(background)

    font_path = "Pollock1CTT Regular.ttf"
    try:
        font_big = ImageFont.truetype(font_path, 32)
        font_small = ImageFont.truetype(font_path, 20)
    except:
        font_big = ImageFont.load_default()
        font_small = ImageFont.load_default()

    purchased = user.get("purchased_features", [])

    vip_priority = [
        "legend", "grandmaster", "titan", "obsidian", "mythic", "emerald", "sapphire",
        "diamond", "champion", "master", "elite", "platinum", "royal", "premium_plus",
        "premium", "vip_plus", "vip", "gold", "silver", "bronze"
    ]

    user_privilege = None
    for key in vip_priority:
        if key in purchased:
            user_privilege = key
            break

    avatar_size = (128, 128)

    if user_privilege:
        avatar_path = f"{user_privilege}.png"
        if os.path.isfile(avatar_path):
            avatar = Image.open(avatar_path).convert("RGBA").resize(avatar_size)
        else:
            avatar = Image.new("RGBA", avatar_size, (100, 100, 100, 255))
    else:
        photos = await context.bot.get_user_profile_photos(user_id, limit=1)
        if photos.total_count > 0:
            file_id = photos.photos[0][-1].file_id
            file = await context.bot.get_file(file_id)
            avatar_bytes = BytesIO()
            await file.download_to_memory(out=avatar_bytes)
            avatar_bytes.seek(0)
            avatar = Image.open(avatar_bytes).convert("RGBA").resize(avatar_size)
        else:
            avatar = Image.new("RGBA", avatar_size, (100, 100, 100, 255))

    vip_border_colors = {
        "bronze": (205, 127, 50, 255),
        "silver": (192, 192, 192, 255),
        "gold": (255, 215, 0, 255),
        "vip": (255, 165, 0, 255),
        "vip_plus": (255, 140, 0, 255),
        "premium": (30, 144, 255, 255),
        "premium_plus": (220, 20, 60, 255),
        "royal": (128, 0, 128, 255),
        "platinum": (229, 228, 226, 255),
        "elite": (255, 105, 180, 255),
        "master": (0, 255, 127, 255),
        "champion": (255, 69, 0, 255),
        "diamond": (185, 242, 255, 255),
        "sapphire": (15, 82, 186, 255),
        "emerald": (80, 200, 120, 255),
        "mythic": (138, 43, 226, 255),
        "obsidian": (30, 30, 30, 255),
        "titan": (128, 128, 128, 255),
        "grandmaster": (255, 215, 0, 255),
        "legend": (255, 0, 0, 255)
    }

    border_color = None
    for key in vip_priority:
        if key in purchased:
            border_color = vip_border_colors.get(key, (180, 180, 255, 255))
            break
    if border_color is None:
        border_color = (180, 180, 255, 255)

    border_size = 4
    mask = Image.new("L", (avatar.size[0] + border_size*2, avatar.size[1] + border_size*2), 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.ellipse((0, 0, mask.size[0], mask.size[1]), fill=255)

    background.paste(border_color, (30 - border_size, 30 - border_size), mask)

    mask_avatar = Image.new("L", avatar.size, 0)
    draw_mask_avatar = ImageDraw.Draw(mask_avatar)
    draw_mask_avatar.ellipse((0, 0, avatar.size[0], avatar.size[1]), fill=255)
    avatar.putalpha(mask_avatar)

    background.paste(avatar, (30, 30), avatar)

    def draw_text_with_neon(draw_obj, position, text, font, base_color="white", neon_color=(100, 100, 255), neon_radius=2):
        x, y = position
        for dx in range(-neon_radius, neon_radius + 1):
            for dy in range(-neon_radius, neon_radius + 1):
                if dx == 0 and dy == 0:
                    continue
                draw_obj.text((x + dx, y + dy), text, font=font, fill=neon_color)
        draw_obj.text(position, text, font=font, fill=base_color)

    nickname = user.get('username', 'Невідомий')
    if "star_emoji" in purchased:
        nickname += " ⭐"

    draw_text_with_neon(draw, (180, 40), f"Профіль: @{nickname}", font_big)

    draw_text_with_neon(draw, (180, 90), f"Баланс: {user.get('balance', 0)} монет", font_small)
    draw_text_with_neon(draw, (180, 120), f"Рівень: {user.get('level', 1)}", font_small)
    draw_text_with_neon(draw, (180, 150), f"Ігор зіграно: {user.get('games_played', 0)}", font_small)
    draw_text_with_neon(draw, (180, 180), f"Виграшів: {user.get('wins', 0)}", font_small)
    draw_text_with_neon(draw, (180, 210), f"Програшів: {user.get('losses', 0)}", font_small)
    draw_text_with_neon(draw, (180, 240), f"Макс серія виграшів: {user.get('max_win_streak', 0)}", font_small)

    current_level = user.get('level', 1)
    games_played = user.get('games_played', 0)

    def level_games_required(level):
        return [0, 10, 30, 60, 100, 150][level] if level < 6 else 150

    games_for_current_level = level_games_required(current_level)
    games_for_next_level = level_games_required(current_level + 1)

    progress = (games_played - games_for_current_level) / max(1, (games_for_next_level - games_for_current_level))
    progress = max(0.0, min(progress, 1.0))

    achievements = user.get("achievements", [])
    badges = {
        "🏆 Переможець 10 ігор поспіль!": "🥇",
        "💰 Виграв 1000 монет!": "💎",
        "🎮 Зіграв 50 ігор!": "🎲"
    }
    ach_text = "Досягнення:\n"
    if achievements:
        for ach in achievements:
            badge = badges.get(ach, "✅")
            ach_text += f"{badge} {ach}\n"
    else:
        ach_text += "Поки що немає досягнень."

    draw.multiline_text((30, 310), ach_text, font=font_small, fill="white")

    output = BytesIO()
    background.save(output, format="PNG")
    output.seek(0)
    await update.message.reply_photo(photo=output)

shop_items_vip = {
    "bronze": {"name": "Bronze", "price": 1000, "description": "Статус Bronze — бронзовий колір ніку."},
    "silver": {"name": "Silver", "price": 2500, "description": "Статус Silver — срібний колір ніку."},
    "gold": {"name": "Gold", "price": 5000, "description": "Статус Gold — золотий колір ніку."},
    "vip": {"name": "VIP", "price": 8000, "description": "Статус VIP — золоте оформлення ніку."},
    "vip_plus": {"name": "VIP+", "price": 12000, "description": "Статус VIP+ — розширене золоте оформлення ніку."},
    "premium": {"name": "Premium", "price": 18000, "description": "Статус Premium — синє оформлення ніку."},
    "premium_plus": {"name": "Premium++", "price": 24000, "description": "Статус Premium++ — червоне оформлення ніку."},
    "royal": {"name": "Royal", "price": 30000, "description": "Статус Royal — королівське оформлення ніку."},
    "platinum": {"name": "Platinum", "price": 40000, "description": "Статус Platinum — платинове оформлення ніку."},
    "elite": {"name": "Elite", "price": 55000, "description": "Статус Elite — елітне оформлення ніку."},
    "master": {"name": "Master", "price": 70000, "description": "Статус Master — майстерське оформлення ніку."},
    "champion": {"name": "Champion", "price": 90000, "description": "Статус Champion — статус чемпіона."},
    "diamond": {"name": "Diamond", "price": 120000, "description": "Статус Diamond — діамантове оформлення ніку."},
    "sapphire": {"name": "Sapphire", "price": 150000, "description": "Статус Sapphire — сапфірове оформлення ніку."},
    "emerald": {"name": "Emerald", "price": 180000, "description": "Статус Emerald — смарагдове оформлення ніку."},
    "mythic": {"name": "Mythic", "price": 220000, "description": "Статус Mythic — міфічне оформлення ніку."},
    "obsidian": {"name": "Obsidian", "price": 270000, "description": "Статус Obsidian — обсидіанове оформлення ніку."},
    "titan": {"name": "Titan", "price": 330000, "description": "Статус Titan — титанове оформлення ніку."},
    "grandmaster": {"name": "Grandmaster", "price": 400000, "description": "Статус Grandmaster — грандмайстер оформлення ніку."},
    "legend": {"name": "Legend", "price": 500000, "description": "Статус Legend — легендарне оформлення ніку."}
}


def escape_md_v2(text: str) -> str:
    escape_chars = r'_*\[\]()~>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users.find_one({"user_id": user_id})

    if not user:
        text = (
            "❌ *Упс\\!* Ви поки що не зареєстровані у системі.\n"
            "Будь ласка, скористайтеся командою /start для реєстрації та початку гри."
        )
        await update.message.reply_text(
            escape_markdown(text, version=2),
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    keyboard = []
    for key, item in shop_items_vip.items():
        owned = key in user.get("purchased_features", [])
        # Экранируем имя товара для вывода в кнопке
        name_escaped = escape_markdown(item['name'], version=2)
        if owned:
            text = f"{name_escaped} ✅"
            keyboard.append([InlineKeyboardButton(text, callback_data="owned")])
        else:
            price_escaped = escape_markdown(str(item['price']), version=2)
            text = f"{name_escaped} 💰 {price_escaped} монет"
            keyboard.append([InlineKeyboardButton(text, callback_data=f"buy_{key}")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    shop_header = (
        "🛒 *Магазин «Дід Панас» — Привілеї*\n\n"
        "Ласкаво просимо до магазину\\! Тут ви можете придбати ексклюзивні привілеї, "
        "які зроблять вашу гру цікавішою та комфортнішою\\.\n\n"
        "⬇️ Натисніть кнопку з привілеєю, яку хочете придбати\\.\n"
        "❗️ Якщо привілея вже придбана, кнопка буде неактивною\\."
    )

    await update.message.reply_text(
        escape_markdown(shop_header, version=2),
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN_V2
    )

    footer = (
        "\n\n💡 *Порада:* Привілеї можна придбати лише через кнопки нижче.\n\n"
        "Якщо у вас недостатньо монет, поповніть баланс для здійснення покупки.\n\n"
        "Дякуємо, що ви з нами! 🌟"
    )

    await update.message.reply_text(
        escape_markdown(footer, version=2),
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def shop_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = users.find_one({"user_id": user_id})

    await query.answer()

    data = query.data

    if data == "owned":
        text = "✅ Ви вже придбали цю привілею."
        await query.edit_message_text(escape_markdown(text, version=2), parse_mode=ParseMode.MARKDOWN_V2)
        return

    if not data.startswith("buy_"):
        text = "❌ Невідома дія."
        await query.edit_message_text(escape_markdown(text, version=2), parse_mode=ParseMode.MARKDOWN_V2)
        return

    item_key = data[4:]

    if item_key not in shop_items_vip:
        text = "❌ Ця привілея більше недоступна."
        await query.edit_message_text(escape_markdown(text, version=2), parse_mode=ParseMode.MARKDOWN_V2)
        return

    if item_key in user.get("purchased_features", []):
        text = "✅ Ви вже придбали цю привілею."
        await query.edit_message_text(escape_markdown(text, version=2), parse_mode=ParseMode.MARKDOWN_V2)
        return

    price = shop_items_vip[item_key]["price"]

    if user["balance"] < price:
        text = (
            f"❌ Недостатньо монет.\n"
            f"Баланс: {user['balance']} монет, потрібно: {price}."
        )
        await query.edit_message_text(escape_markdown(text, version=2), parse_mode=ParseMode.MARKDOWN_V2)
        return

    users.update_one(
        {"user_id": user_id},
        {
            "$inc": {"balance": -price},
            "$push": {"purchased_features": item_key}
        }
    )

    item_name = shop_items_vip[item_key]["name"]
    text = f"🎉 Ви успішно придбали привілею *{escape_markdown(item_name, version=2)}*!"

    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN_V2)


async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top_users = list(users.find().sort("balance", -1).limit(10))

    if not top_users:
        await update.message.reply_text("❌ Поки що немає зареєстрованих гравців.")
        return

    medals = ["🥇", "🥈", "🥉"]
    msg = "🏆 *Топ 10 гравців за балансом* 🏆\n\n"
    for i, user in enumerate(top_users, start=1):
        username = user.get("username") or f"User{user['user_id']}"
        balance = user.get("balance", 0)
        medal = medals[i-1] if i <= 3 else f"{i}️⃣"
        msg += f"{medal} *{username}* — 💰 {balance} монет\n"

    msg += "\n🎉 Вітаємо наших чемпіонів та бажаємо удачі всім учасникам! 🍀"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def bot_added_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            leave_time = datetime.utcnow() + timedelta(minutes=1)
            await update.message.reply_text(
                "🤖 Вітаю! Я — тестова версія цього Telegram-бота.\n\n"
                "⚠️ Зверніть увагу, що ця версія працюватиме лише тимчасово.\n"
                "💡 Ваші ідеї, побажання та будь-який фідбек дуже важливі для нас!\n"
                "Будь ласка, надсилайте їх автору бота: @An1h3lia\n\n"
                "📌 Підписуйтеся на оновлення, щоб не пропустити нові версії і корисні функції.\n\n"
                "Щоб почати роботу з ботом, будь ласка, введіть команду /start.\n\n"
                "Дякуємо за розуміння та підтримку! 🤝"
            )
            return

async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    sender = users.find_one({"user_id": user_id})

    if not sender:
        await update.message.reply_text("❌ Ви не зареєстровані. Використайте /start для реєстрації.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("❌ Використання: /pay <username> <amount>\nНаприклад: /pay @didpanas 100")
        return

    target_username = context.args[0].lstrip("@")

    try:
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Кількість монет має бути цілим числом.")
        return

    if amount <= 0:
        await update.message.reply_text("❌ Кількість монет має бути більше нуля.")
        return

    if sender["balance"] < amount:
        await update.message.reply_text(f"❌ У вас недостатньо монет для переказу. Ваш баланс: {sender['balance']}")
        return

    recipient = users.find_one({
        "username": {"$regex": f"^{target_username}$", "$options": "i"}
    })

    if not recipient:
        await update.message.reply_text(f"❌ Користувача @{target_username} не знайдено.")
        return

    if recipient["user_id"] == user_id:
        await update.message.reply_text("❌ Ви не можете переказувати монети собі.")
        return

    users.update_one({"user_id": user_id}, {"$inc": {"balance": -amount}})
    users.update_one({"user_id": recipient["user_id"]}, {"$inc": {"balance": amount}})

    await update.message.reply_text(
        f"✅ Ви успішно переказали {amount} монет користувачу @{recipient['username']}.\n"
        f"Ваш новий баланс: {sender['balance'] - amount} монет."
    )

    try:
        await context.bot.send_message(
            chat_id=recipient["user_id"],
            text=f"🎉 Вам надійшло {amount} монет від користувача @{sender['username']}!"
        )
    except Exception:
        pass

async def give_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = 6244270354 
    if update.effective_user.id != admin_id:
        await update.message.reply_text("❌ У вас немає прав для виконання цієї команди.")
        return

    result = users.update_many({}, {"$inc": {"balance": 1000000}})
    await update.message.reply_text(f"✅ Всім користувачам додано по 1 000 000 монет. Оновлено записів: {result.modified_count}")


async def give(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = 6244270354 
    if update.effective_user.id != admin_id:
        await update.message.reply_text("❌ У вас немає прав для виконання цієї команди.")
        return

    args = context.args
    if len(args) != 2:
        await update.message.reply_text(
            "❌ Неправильний формат команди.\n"
            "Використовуйте: /give <username> <кількість>\n"
            "Наприклад: /give @username 1000"
        )
        return

    username = args[0].lstrip("@").lower()
    try:
        amount = int(args[1])
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Некоректні дані. Кількість має бути додатнім числом.")
        return

    user_doc = users.find_one({"username": {"$regex": f"^{username}$", "$options": "i"}})
    if not user_doc:
        await update.message.reply_text(f"❌ Користувача з username @{username} не знайдено в базі.")
        return

    target_user_id = user_doc["user_id"]

    result = users.update_one({"user_id": target_user_id}, {"$inc": {"balance": amount}})
    if result.modified_count == 0:
        await update.message.reply_text(f"❌ Не вдалося оновити баланс користувача @{username}.")
    else:
        await update.message.reply_text(f"✅ Користувачу @{username} додано {amount} монет.")


active_challenges = {}

def generate_math_problem():
    operations = ['+', '-', '*', '//']
    op = random.choice(operations)

    if op == '*':
        a = random.randint(10, 30)
        b = random.randint(5, 20)
        reward = 3000 + (a + b) * 20
    elif op == '//':
        b = random.randint(2, 15)
        answer = random.randint(2, 20)
        a = b * answer
        reward = 4000 + (a + b) * 30
        problem_text = (
            f"🔢 Математичний виклик!\n"
            f"Обчисли: {a} {op} {b} = ?\n"
            f"Перший, хто правильно розв’яже — отримає нагороду у {reward} монет! 🎯🧠"
        )
        return problem_text, answer, reward
    else:
        a = random.randint(20, 80)
        b = random.randint(10, 50)
        reward = 2000 + (a + b) * 10

    if op == '+':
        answer = a + b
    elif op == '-':
        answer = a - b
    elif op == '*':
        answer = a * b

    problem_text = (
        f"🔢 Математичний виклик!\n"
        f"Обчисли: {a} {op} {b} = ?\n"
        f"Перший, хто правильно розв’яже — отримає нагороду у {reward} монет! 🎯🧠"
    )
    return problem_text, answer, reward

async def send_math_challenge(context: ContextTypes.DEFAULT_TYPE):
    active_chats = context.bot_data.get("active_chats", set())
    for chat_id in active_chats:
        if chat_id in active_challenges and not active_challenges[chat_id]["answered"]:
            continue
        problem_text, answer, reward = generate_math_problem()
        try:
            msg = await context.bot.send_message(chat_id=chat_id, text=problem_text)
            active_challenges[chat_id] = {
                "answer": answer,
                "reward": reward,
                "answered": False,
                "message_id": msg.message_id
            }
        except Exception as e:
            print(f"Не можу надіслати повідомлення в чат {chat_id}: {e}")

async def math_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if chat_id not in active_challenges or active_challenges[chat_id]["answered"]:
        return

    challenge = active_challenges[chat_id]

    if not text.isdigit():
        return

    if int(text) == challenge["answer"]:
        challenge["answered"] = True
        reward = challenge["reward"]

        user = users.find_one({"user_id": user_id})
        if user:
            new_balance = user.get("balance", 0) + reward
            users.update_one({"user_id": user_id}, {"$set": {"balance": new_balance}})

        await update.message.reply_text(
            f"🎉 Вітаємо, {update.effective_user.first_name}! 🎓\n"
            f"Твоя правильна відповідь — це справжній триумф розуму! 🧠💥\n"
            f"Ти отримуєш заслужені *{reward}* монет! Готуйся до наступного виклику! 🚀",
            parse_mode='Markdown'
        )

        del active_challenges[chat_id]

async def start_math_challenge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    active_chats = context.bot_data.get("active_chats", set())
    active_chats.add(chat_id)
    context.bot_data["active_chats"] = active_chats
    await update.message.reply_text(
        "✅ Чат підключено до математичних викликів!\n"
        "Приклади будуть з’являтися кожні 1 хвилин — тренуй свій мозок та збирай монети! 💡💰"
    )

async def stop_math_challenge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    active_chats = context.bot_data.get("active_chats", set())
    active_chats.discard(chat_id)
    context.bot_data["active_chats"] = active_chats
    await update.message.reply_text(
        "🛑 Математичні виклики для цього чату призупинено.\n"
        "Дякуємо за участь! Повернись за новими завданнями будь-коли! 📚✨"
    )

async def periodic_task(application: Application):
    while True:
        await send_math_challenge(application)
        await asyncio.sleep(60)

async def periodic_task(context: ContextTypes.DEFAULT_TYPE):
    await send_math_challenge(context)

def main():
    bot_token = "8040782659:AAFgYkj067UhF8_eg13_m8UJCseE0Ur224w"
    app = ApplicationBuilder().token(bot_token).build()

    slots_conv = ConversationHandler(
        entry_points=[CommandHandler("slots", slots_bet)],
        states={SLOTS_BET: [MessageHandler(filters.TEXT & ~filters.COMMAND, slots_bet)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(slots_conv)

    coin_conv = ConversationHandler(
        entry_points=[CommandHandler("coin", coin_start)],
        states={BET: [MessageHandler(filters.TEXT & ~filters.COMMAND, coin_bet)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(coin_conv)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("top", top_command))
    app.add_handler(CommandHandler("shop", shop))
    app.add_handler(CommandHandler("pay", pay))
    app.add_handler(CommandHandler("give_all", give_all))
    app.add_handler(CommandHandler("give", give))
    app.add_handler(CommandHandler("start_math_challenge", start_math_challenge))
    app.add_handler(CommandHandler("stop_math_challenge", stop_math_challenge))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, math_answer_handler))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, bot_added_to_group))
    app.add_handler(CallbackQueryHandler(shop_button_handler))

    print("🤖 Спроба запуску бота...")
    try:
        app.run_polling()
    except Exception as e:
        print(f"❌ Помилка під час запуску бота: {e}")
    else:
        print("✅ Бот успішно запущений!")

if __name__ == "__main__":
    main()