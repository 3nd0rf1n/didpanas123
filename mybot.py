import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
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
from telegram.error import RetryAfter
import re
import os
from aiohttp  import web 
from urllib.parse import quote_plus

username = "3ndorfin"
password = quote_plus("SashaTretyak")  # на випадок спецсимволів

mongo_url = f"mongodb+srv://{username}:{password}@didpanas.ijv2rrd.mongodb.net/?retryWrites=true&w=majority&appName=didpanas"

client = MongoClient(mongo_url)
db = client["didpanas"]
users = db["panas_users"]

BET = range(1)
SLOTS_BET = range(1)

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

    await asyncio.sleep(0.5)

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
            "⏹ Щоб скасувати гру, введіть /cancel."
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
    for _ in range(spins):
        current_spin = [random.choice(SLOT_SYMBOLS) for _ in range(3)]
        display = " | ".join(current_spin)
        try:
            await message.edit_text(f"🎰 Обертаємо барабани...\n\n{display}")
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
            await message.edit_text(f"🎰 Обертаємо барабани...\n\n{display}")
        await asyncio.sleep(1)

    if len(set(current_spin)) == 1:
        winnings = bet * 5
        win = 1
        lose = 0
    elif len(set(current_spin)) == 2:
        winnings = bet * 2
        win = 1
        lose = 0
    else:
        winnings = -bet
        win = 0
        lose = 1

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

    if winnings > 0:
        result_msg = f"🎉 Вітаємо! Ви виграли {winnings} монет!\n{display}"
    else:
        result_msg = f"💀 На жаль, ви програли {bet} монет.\n{display}"

    msg = (
        f"{result_msg}\n\n"
        f"💰 Ваш новий баланс: {new_balance} монет\n"
        f"📊 Статистика: {user.get('wins', 0) + win} виграшів, {user.get('losses', 0) + lose} програшів\n"
        f"🎲 Ігор зіграно: {new_games_played}\n"
        f"⭐ Поточний рівень: {new_level}"
    )

    await message.edit_text(msg)

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

    # Спробуємо знайти найвищу привілею
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
        await update.message.reply_text("❌ Ви не зареєстровані. Напишіть /start")
        return

    shop_text = "🛒 *Магазин «Дід Панас» — Привілеї*\n\n"
    for key, item in shop_items_vip.items():
        owned = "✅ Вже придбано" if key in user.get("purchased_features", []) else f"💰 Ціна: {item['price']} монет"
        name_esc = escape_md_v2(item['name'])
        owned_esc = escape_md_v2(owned)
        shop_text += f"{name_esc}: {owned_esc}\n"

    suffix = "\nЩоб купити, введи команду:\n/buy <назва_привілеї>\nНаприклад: /buy gold"
    suffix_esc = escape_md_v2(suffix)
    shop_text += suffix_esc

    await update.message.reply_text(shop_text, parse_mode=ParseMode.MARKDOWN_V2)

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users.find_one({"user_id": user_id})

    if not user:
        await update.message.reply_text(
            "❌ Ви наразі не зареєстровані в системі.\n"
            "Будь ласка, скористайтеся командою /start для реєстрації та початку гри."
        )
        return

    if not context.args:
        await update.message.reply_text(
            "❌ Ви не вказали назву привілеї.\n"
            "Будь ласка, введіть команду у форматі:\n"
            "/buy <назва_привілеї>\n"
            "Наприклад: /buy gold"
        )
        return

    item_key = context.args[0].lower()

    if item_key not in shop_items_vip:
        await update.message.reply_text(
            "❌ Обрана привілея відсутня у магазині.\n"
            "Будь ласка, перевірте правильність написання та спробуйте знову."
        )
        return

    if item_key in user.get("purchased_features", []):
        await update.message.reply_text(
            "✅ Ви вже придбали цю привілею.\n"
            "Дякуємо за вашу підтримку! Ви можете продовжувати насолоджуватися всіма перевагами."
        )
        return

    price = shop_items_vip[item_key]["price"]
    if user["balance"] < price:
        await update.message.reply_text(
            f"❌ Недостатньо монет для здійснення покупки.\n"
            f"Ваш поточний баланс: {user['balance']} монет.\n"
            f"Для придбання цієї привілеї необхідно: {price} монет."
        )
        return

    # Оновлення бази даних: віднімання коштів і додавання привілеї
    users.update_one(
        {"user_id": user_id},
        {
            "$inc": {"balance": -price},
            "$push": {"purchased_features": item_key}
        }
    )

    item_name = shop_items_vip[item_key]["name"]
    item_description = shop_items_vip[item_key].get("description", "")

    await update.message.reply_text(
        f"🎉 Вітаємо! Ви успішно придбали привілею *{item_name}*.\n\n"
        f"ℹ️ Опис: {item_description}\n"
        f"💰 З вашого балансу було списано: {price} монет.\n"
        f"💼 Тепер ви можете користуватися всіма перевагами цієї привілеї.\n\n"
        "Дякуємо за довіру та бажаємо вам успішної гри! 🍀",
        parse_mode=ParseMode.MARKDOWN
    )

    users.update_one(
        {"user_id": user_id},
        {
            "$inc": {"balance": -price},
            "$push": {"purchased_features": item_key}
        }
    )

    name_esc = escape_md_v2(shop_items_vip[item_key]['name'])

    await update.message.reply_text(
        f"🎉 Ви успішно придбали *{name_esc}*!",
        parse_mode=ParseMode.MARKDOWN_V2
    )



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


async def handle(request):
    return web.Response(text="✅ Bot is running!")

app_web = web.Application()
app_web.add_routes([web.get('/', handle)])

if __name__ == '__main__':
    import asyncio
    from telegram.ext import Application

    async def run_all():
        telegram_app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()

        telegram_app.add_handler(CommandHandler("start", start))
        telegram_app.add_handler(CommandHandler("balance", balance))
        telegram_app.add_handler(CommandHandler("daily", daily))
        telegram_app.add_handler(CommandHandler("profile", profile))
        telegram_app.add_handler(CommandHandler("shop", shop))
        telegram_app.add_handler(CommandHandler("buy", buy))

        coin_conv = ConversationHandler(
            entry_points=[CommandHandler("coin", coin_start)],
            states={BET: [MessageHandler(filters.TEXT & ~filters.COMMAND, coin_bet)]},
            fallbacks=[CommandHandler("cancel", cancel)]
        )
        telegram_app.add_handler(coin_conv)

        slots_conv = ConversationHandler(
            entry_points=[CommandHandler("slots", slots_bet)],
            states={SLOTS_BET: [MessageHandler(filters.TEXT & ~filters.COMMAND, slots_bet)]},
            fallbacks=[CommandHandler("cancel", cancel)]
        )
        telegram_app.add_handler(slots_conv)

        await asyncio.gather(
            telegram_app.run_polling(),
            web._run_app(app_web, host='0.0.0.0', port=8000)
        )

    asyncio.run(run_all())