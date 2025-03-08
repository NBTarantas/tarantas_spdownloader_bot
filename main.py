
import re
import shutil
import subprocess
import pysofaconventions as sofa
import time
from functools import wraps

import requests
import yt_dlp

import numpy as np
import soundfile as sf
from scipy import signal
from scipy.signal import butter, lfilter
from pydub import AudioSegment


import telebot

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import logging

from constants.allowed_users import ALLOWED_USERS
from constants.admin_users import ADMIN_USERS
from outh_data import YOUTUBE_API_KEY
from sp_tools.markup_creation import create_markup

from spotify.spotify_logik import get_tracks_from_playlist, download_and_send_track, bot, split_file, \
    download_track_for_zip, DownloadProgress, get_track, get_track_single, search_spotify_tracks
from url_checker.url_checker import is_spotify_playlist_url, is_spotify_track_url, is_yt_track_url, is_add_command, \
    is_deezer_playlist_url, is_deezer_track_url, is_video_link, is_inst_link
import os

from datetime import datetime
import sys

import deezer

from youtube.youtube_logik import download_youtube_track, download_youtube_track_for_zip

telebot.apihelper.TIMEOUT = 60

# Створюємо папку для логів, якщо її немає
log_directory = "logs"
if not os.path.exists(log_directory):
    os.makedirs(log_directory)

# Створюємо ім'я файлу логу з поточною датою
log_filename = os.path.join(log_directory, f"bot_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log")

# Налаштування форматування логів
log_format = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(funcName)s() - %(message)s'
)

# Налаштування обробника файлових логів
file_handler = logging.FileHandler(log_filename, encoding='utf-8')
file_handler.setFormatter(log_format)
file_handler.setLevel(logging.DEBUG)

# Налаштування обробника консольних логів
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_format)
console_handler.setLevel(logging.INFO)

# Налаштування кореневого логера
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
logger.addHandler(file_handler)
logger.addHandler(console_handler)


# Додаємо перехоплювач необроблених винятків
def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logger.critical("Необроблена помилка:", exc_info=(exc_type, exc_value, exc_traceback))


sys.excepthook = handle_exception

# Словники для зберігання даних користувачів
search_sessions = {}
user_track_yt = {}
user_tracks = {}
user_v_or_a = {}
user_delivery_method = {}  # Зберігання вибраного способу надсилання
user_temp_folders = {}  # Зберігання шляхів до тимчасових папок
# Додамо словник для зберігання вибраного формату користувача
user_audio_format = {}
# URL для пошуку відео
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"

# Функція для формування тексту результатів
def format_results(items):
    results = ""
    for item in items:
        title = item["snippet"]["title"]
        video_id = item["id"]["videoId"]
        results += f"[{title}](https://www.youtube.com/watch?v={video_id})\n"
    return results


def search_youtube(query, page_token=None):
    # Додаємо параметри для пошуку тільки музики
    url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&type=video&videoCategoryId=10&q={query}&key={YOUTUBE_API_KEY}&maxResults=5"
    if page_token:
        url += f"&pageToken={page_token}"
    response = requests.get(url)
    return response.json()


def create_search_results_keyboard(items):
    """Створює інлайн клавіатуру з результатами пошуку"""
    markup = InlineKeyboardMarkup(row_width=1)

    for item in items:
        title = item["snippet"]["title"]
        video_id = item["id"]["videoId"]
        url = f"https://www.youtube.com/watch?v={video_id}"

        # Створюємо кнопку для кожного треку
        markup.add(InlineKeyboardButton(
            text=title,
            callback_data=f"youtube_url:{video_id}"
        ))

    return markup


@bot.message_handler(func=lambda message: message.text.lower().startswith("!юті "))
def handle_search(message):
    query = message.text[5:]  # Видаляємо "знайти " з початку
    search_results = search_youtube(query)
    items = search_results.get("items", [])
    next_page_token = search_results.get("nextPageToken")
    prev_page_token = None

    # Створюємо клавіатуру з результатами
    markup = create_search_results_keyboard(items)

    # Додаємо кнопки навігації
    navigation_row = []
    if prev_page_token:
        navigation_row.append(InlineKeyboardButton(
            "⬅️ Назад",
            callback_data=f"search:{query}:{prev_page_token}"
        ))
    if next_page_token:
        navigation_row.append(InlineKeyboardButton(
            "➡️ Далі",
            callback_data=f"search:{query}:{next_page_token}"
        ))
    if navigation_row:
        markup.row(*navigation_row)

    bot.send_message(
        message.chat.id,
        f"🎵 Результати пошуку для '{query}':",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("youtube_url:"))
def handle_youtube_url_selection(call):
    video_id = call.data.split(":")[1]
    url = f"https://www.youtube.com/watch?v={video_id}"
    user_id = call.from_user.id
    if user_id in ALLOWED_USERS: # Надсилаємо URL як нове повідомлення
        class MockMessage:
            def __init__(self, chat_id, from_user, text, message_id):
                self.chat = type('obj', (object,), {'id': chat_id})
                self.from_user = from_user
                self.text = text
                self.message_id = message_id

        # Створюємо фіктивне повідомлення з URL та ID повідомлення
        mock_message = MockMessage(
            chat_id=call.message.chat.id,
            from_user=call.from_user,
            text=url,
            message_id=call.message.message_id
        )

        # Тепер передаємо це повідомлення в handle_yt_track
        handle_yt_track(mock_message)
    else:
        bot.send_message(
            call.message.chat.id,
            url
        )

@bot.callback_query_handler(func=lambda call: call.data.startswith("search:"))
def handle_pagination(call):
    _, query, page_token = call.data.split(":")
    search_results = search_youtube(query, page_token)
    items = search_results.get("items", [])
    next_page_token = search_results.get("nextPageToken")
    prev_page_token = search_results.get("prevPageToken")

    # Створюємо нову клавіатуру з результатами
    markup = create_search_results_keyboard(items)

    # Додаємо кнопки навігації
    navigation_row = []
    if prev_page_token:
        navigation_row.append(InlineKeyboardButton(
            "⬅️ Назад",
            callback_data=f"search:{query}:{prev_page_token}"
        ))
    if next_page_token:
        navigation_row.append(InlineKeyboardButton(
            "➡️ Далі",
            callback_data=f"search:{query}:{next_page_token}"
        ))
    if navigation_row:
        markup.row(*navigation_row)

    bot.edit_message_text(
        f"🎵 Результати пошуку для '{query}':",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

def check_user_access(func):
    @wraps(func)
    def wrapper(message, *args, **kwargs):
        if not hasattr(message, 'from_user'):
            # Для callback queries
            if hasattr(message, 'message'):
                user_id = message.from_user.id
            else:
                return
        else:
            user_id = message.from_user.id

        if user_id not in ALLOWED_USERS:
            bot.send_message(
                message.chat.id,
                f"Your ID: {user_id} \nНадішли мені '!юті \"Назва треку\"' - для пошуку на YouTube \n'!споті \"Назва треку\"' - для пошуку на Spotify \n Я можу створити SPEEDUP та Bass Boost. Також я можу накладати ефект ЕХО та 8D audio. \n Просто надішли мені файл і слідуй інструкціям на екрані)",
                parse_mode="HTML"
            )
            #bot.send_message(message.chat.id, "Окей... Секундочку, додаю вас до списку дозволених користувачів")
            #ALLOWED_USERS.append(int(user_id))
            #with open("constants/allowed_users.py", "w") as file:
                #file.write(f"ALLOWED_USERS = {ALLOWED_USERS}\n")
            #bot.send_message(message.chat.id, "Все! Ваш ідентифікатор додано! Будь ласка почніть розмову спочатку.")
            return
        return func(message, *args, **kwargs)

    return wrapper

def check_user_admin_access(func):
    @wraps(func)
    def wrapper(message, *args, **kwargs):
        if not hasattr(message, 'from_user'):
            # Для callback queries
            if hasattr(message, 'message'):
                user_id = message.from_user.id
            else:
                return
        else:
            user_id = message.from_user.id

        if user_id not in ADMIN_USERS:
            bot.reply_to(message, f"||\n{user_id}\n|| is not in sudoers file", parse_mode="MarkdownV2")
            return
        return func(message, *args, **kwargs)

    return wrapper


@bot.message_handler(func=lambda message: is_add_command(message.text))
@check_user_access
@check_user_admin_access
def add_allowed_users(message):
    match = re.match(r"def add_new_user\[(\d+(?:, \d+)*)]", message.text)

    if match:
        # Отримуємо числа з рядка і перетворюємо їх у список
        user_ids = match.group(1).split(", ")

        # Перетворюємо на список цілих чисел
        user_ids = [int(user_id) for user_id in user_ids]

        # Додаємо нові ID до списку дозволених користувачів
        ALLOWED_USERS.extend(user_ids)

        # Оновлюємо Python файл зі списком дозволених користувачів
        with open("constants/allowed_users.py", "w") as file:
            file.write(f"ALLOWED_USERS = {ALLOWED_USERS}\n")

        # Вивести новий список
        bot.reply_to(message, f"Нові користувачі додані: *{user_ids}*", parse_mode="MarkdownV2")
        bot.reply_to(message, f"Оновлений список дозволених ID: ||{ALLOWED_USERS}||", parse_mode="MarkdownV2")
    else:
        bot.reply_to(message, "Формат неправильний. Використовуйте: *def add_new_user\n[числа, числа, ...]\n*", parse_mode="MarkdownV2")


def get_deezer_track(track_url):
    """Отримує інформацію про трек з Deezer"""
    client = deezer.Client()
    track_id = re.search(r'track/(\d+)', track_url).group(1)
    track = client.get_track(track_id)

    return [{
        "name": track.title,
        "artist": track.artist.name
    }]


def get_deezer_tracks_from_playlist(playlist_url):
    """Отримує треки з плейлиста Deezer"""
    client = deezer.Client()
    playlist_id = re.search(r'playlist/(\d+)', playlist_url).group(1)
    playlist = client.get_playlist(playlist_id)

    tracks = []
    for track in playlist.tracks:
        tracks.append({
            "name": track.title,
            "artist": track.artist.name
        })

    return tracks

@bot.message_handler(func=lambda message: is_deezer_track_url(message.text))
@check_user_access
def handle_deezer_track(message):
    try:
        track = get_deezer_track(message.text)
        user_tracks[message.from_user.id] = track

        # Спочатку питаємо про формат
        markup = create_format_selection_keyboard(message)
        bot.reply_to(
            message,
            "Виберіть формат аудіо:",
            reply_markup=markup
        )

    except Exception as e:
        logger.exception(f"Error handling Deezer track: {str(e)}")
        bot.reply_to(message, f"Виникла помилка при обробці треку Deezer: {str(e)}")

def download_video(url, chat_id, user_id):
    try:
        temp_folder = create_temp_folder(user_id)
        temp_path = f"{temp_folder}/track.mp4"

        progress = DownloadProgress(bot, chat_id, url)
        progress.send_initial_message()

        def ydl_progress_hook(d):
            if d['status'] == 'downloading':
                try:
                    downloaded = d.get('downloaded_bytes', 0)
                    total = d.get('total_bytes', 0) or d.get('total_bytes_estimate', 0)
                    if total:
                        p = int(20 + (downloaded / total * 40))
                        progress.update_progress(p)
                except:
                    pass

        ydl_opts = {
            "format": 'best',
            'ffmpeg_location': 'D:\\NBurc\\AI_App\\FFMpeg',
            "outtmpl": temp_path,
            "progress_hooks": [ydl_progress_hook],
            'verbose': True,
        }

        # Завантаження
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        progress.update_progress(100)
        progress.complete()

        bot.send_video(chat_id, open(temp_path, "rb"))
    except Exception as e:
        bot.send_message(chat_id, f"Ups! ERROR: {e}")


@bot.message_handler(func=lambda message: is_inst_link(message.text))
@check_user_access
def handle_video(message):
    user = message.from_user.id
    url = message.text
    chat_id = message.chat.id
    download_video(url, chat_id, user)

@bot.message_handler(func=lambda message: is_video_link(message.text))
@check_user_access
def handle_video(message):
    user = message.from_user.id
    url = message.text
    chat_id = message.chat.id
    download_video(url, chat_id, user)

@bot.message_handler(func=lambda message: is_deezer_playlist_url(message.text))
@check_user_access
def handle_deezer_playlist(message):
    try:
        tracks = get_deezer_tracks_from_playlist(message.text)
        user_tracks[message.from_user.id] = tracks

        # Спочатку питаємо про формат
        markup = create_format_selection_keyboard(message)
        bot.reply_to(
            message,
            "Виберіть формат аудіо:",
            reply_markup=markup
        )

    except Exception as e:
        logger.exception(f"Error handling Deezer playlist: {str(e)}")
        bot.reply_to(message, f"Виникла помилка при обробці плейлиста Deezer: {str(e)}")

def get_youtube_metadata(url):
    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
        'skip_download': True,
        'no_warnings': True,
        'format': None  # Не отримуємо інформацію про формати
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.cache.remove()  # Очищаємо кеш
            info = ydl.extract_info(url, download=False, process=False)  # process=False для швидшої роботи
            return {
                'title': info.get('title', 'Unknown Title'),
                'author': info.get('uploader', 'Unknown Artist'),
                'url': url
            }
    except Exception as e:
        logger.exception(f"Error getting YouTube metadata: {str(e)}")
        return {
            'title': 'Unknown Title',
            'author': 'Unknown Artist',
            'url': url
        }

def create_format_selection_keyboard(message):
    user_id = message.from_user.id
    if user_id in ADMIN_USERS:
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("MP3", callback_data="format_mp3"),
            InlineKeyboardButton("M4A", callback_data="format_m4a"),
            InlineKeyboardButton("WAV", callback_data="format_wav"),
            InlineKeyboardButton("FLAC", callback_data="format_flac")
        )
        return markup
    else:
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("MP3", callback_data="format_mp3"),
            InlineKeyboardButton("M4A", callback_data="format_m4a"),
            InlineKeyboardButton("FLAC", callback_data="format_flac")
        )
        return markup

def create_delivery_method_keyboard():
    """Створює клавіатуру для вибору способу надсилання"""
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("По одному", callback_data="delivery_single"),
        InlineKeyboardButton("В ZIP архіві", callback_data="delivery_zip")
    )
    return markup


def create_tracks_keyboard(tracks):
    """Створює клавіатуру з треками"""
    markup = InlineKeyboardMarkup(row_width=1)

    for i, track in enumerate(tracks):
        if track.get('is_youtube'):
            # Використовуємо вже отримані метадані
            track_name = f"{track['author']} - {track['title']}"
        else:
            # Обробка Spotify треків залишається без змін
            track_name = f"{track['artist']} - {track['name']}"

        markup.add(InlineKeyboardButton(
            text=track_name,
            callback_data=f"track_{i}"
        ))

    markup.add(InlineKeyboardButton("Завантажити все", callback_data="download_all"))
    return markup

@bot.message_handler(commands=['start'])
@check_user_access
def start_message(message):
    """Обробник команди /start"""
    bot.send_message(message.chat.id, "Привіт! \n<b>Я вмію завантажувати музику з</b>: \n\n🔥плейлистів Spotify та \n🔥Deezer (формату \"deezer.com/en/playlist...\" \n🔥з посилань на трек Spotify, \n🔥Youtube (YouTube Music) \n\n<b>в якісних форматах:</b> \n🔥mp3, \n🔥m4a, \n🔥flac! \n\nА також шукати музику за тригером \n<b>🔥\"!юті\"</b> - на YouTube, \n<b>🔥\"!споті\"</b> - на платформі Spotify! \n\n\n<i>Використовуйте пошук на Spotify, якщо маєте точну назву трека який шукаєте! \nінакше результат пошуку Вас не зможе задовольнити</i>", parse_mode="HTML")
    bot.send_message(message.chat.id, "Можу завантажити невелике відео <b>(до 50мб)</b> \n\nЯ підтримую такі платформи: \n<b>🔥Instagram</b> \n<b>🔥TikTok</b> \n<b>🔥YouTube Shorts</b> \n<b>🔥Vimeo</b>", parse_mode="HTML")
    bot.send_message(message.chat.id, "\n Я можу створити <b>SPEEDUP</b> та <b>Bass Boost</b>. Також я можу накладати ефект <b>ЕХО</b> та 🔥<b>8D audio</b>. \n Просто надішли мені файл і слідуй інструкціям на екрані)", parse_mode="HTML")
@bot.message_handler(func=lambda message: message.text.lower().startswith("!споті "))
def handle_search(message):
    query = message.text[7:]  # Видаляємо "знайти " з початку
    search_results = search_spotify_tracks(query)

    if not search_results:
        bot.send_message(message.chat.id, f"Нічого не знайдено для '{query}' 😢")
        return

    markup = InlineKeyboardMarkup(row_width=1)
    response_text = f"🎵 Результати пошуку для '{query}':\n"

    for track in search_results:
        response_text += f"[{track['artist']} - {track['name']}]({track['url']})\n"
        markup.add(InlineKeyboardButton(f"{track['artist']} - {track['name']}", url=track['url']))

    bot.send_message(message.chat.id, response_text, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(func=lambda message: is_spotify_track_url(message.text))
@check_user_access
def handle_spotify_track(message):
    try:
        track = get_track_single(message.text)

        # Зберігаємо список треків (навіть якщо один)
        user_tracks[message.from_user.id] = [{
            "name": track["name"],
            "artist": track["artist"],
            "album": track["album"],
            "url": track["url"],
            "is_youtube": False  # Додаємо прапорець, щоб уникнути помилки
        }]

        bot.send_message(
            message.chat.id,
            f"🔍 Знайдено: {track['artist']} - {track['name']}\n🎵 Альбом: {track['album']}"
        )

        # Пошук відео на YouTube
        yt_query = f"{track['artist']} - {track['name']}"
        search_results = search_youtube(yt_query)
        items = search_results.get("items", [])

        if items:
            video_url = f"https://www.youtube.com/watch?v={items[0]['id']['videoId']}"
            bot.send_message(message.chat.id, f"🎬 Найкращий збіг: [YouTube]({video_url})", parse_mode="Markdown")

        # Запитуємо формат завантаження
        markup = create_format_selection_keyboard(message)
        bot.send_message(
            message.chat.id,
            "Вибери формат аудіо:",
            reply_markup=markup
        )

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка: {str(e)}")


@bot.message_handler(func=lambda message: is_yt_track_url(message.text))
@check_user_access
def handle_yt_track(message):
    """Обробник для завантаження аудіо з YouTube"""
    user_track_yt[message.from_user.id] = message.text

    # Швидке отримання метаданих
    metadata = get_youtube_metadata(message.text)

    # Зберігаємо URL та метадані в тимчасове сховище
    user_tracks[message.from_user.id] = [{
        "url": message.text,
        "is_youtube": True,
        "title": metadata['title'],
        "author": metadata['author']
    }]

    # Запитуємо формат
    markup = create_format_selection_keyboard(message)
    bot.reply_to(
        message,
        f"Знайдено трек: {metadata['author']} - {metadata['title']}\nВиберіть формат аудіо:",
        reply_markup=markup
    )

@bot.message_handler(func=lambda message: is_spotify_playlist_url(message.text))
@check_user_access
def handle_playlist_url(message):
    """Оновлений обробник URL плейлиста"""
    try:
        # Отримуємо треки
        tracks = get_tracks_from_playlist(message.text)
        user_tracks[message.from_user.id] = tracks

        # Спочатку питаємо про формат
        markup = create_format_selection_keyboard(message)
        bot.reply_to(
            message,
            "Виберіть формат аудіо:",
            reply_markup=markup
        )

    except Exception as e:
        logger.exception(f"Error handling playlist: {str(e)}")
        bot.reply_to(message, f"Виникла помилка при обробці плейлиста: {str(e)}")

def create_temp_folder(user_id):
    """Створює тимчасову папку для користувача"""
    folder_name = f"temp_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    path = f"temp/{folder_name}"
    os.makedirs(path, exist_ok=True)
    return path


def cleanup_temp_folder(folder_path):
    """Видаляє тимчасову папку та її вміст"""
    try:
        if os.path.exists(folder_path):
            for file in os.listdir(folder_path):
                os.remove(os.path.join(folder_path, file))
            os.rmdir(folder_path)
    except Exception as e:
        logger.exception(f"Error cleaning up temp folder: {str(e)}")
if not os.path.exists("downloads"):
    os.makedirs("downloads")

@bot.message_handler(content_types=['audio'])
def handle_audio(message):
    markup = telebot.types.ReplyKeyboardMarkup(one_time_keyboard=True)
    markup.add('BassBoost', 'SpeedUp', 'Reverb', '8d')
    msg = bot.reply_to(message, 'Виберіть опцію:', reply_markup=markup)
    bot.register_next_step_handler(msg, process_option_step, message.audio.file_id)

def convert_to_wav(input_path, output_path):
    audio = AudioSegment.from_file(input_path)
    audio.export(output_path, format="wav")
def convert_to_m4a(input_path, output_path):
    audio = AudioSegment.from_file(input_path)
    audio.export(output_path, format="m4a")

def process_option_step(message, file_id):
    if message.text == 'BassBoost':
        bot.reply_to(message, 'Зачекайте! Обробка триває...')
        process_dance_eq_step(message, file_id)
    elif message.text == 'Reverb':
        bot.reply_to(message, 'Зачекайте! Обробка триває...')
        process_reverb_step(message, file_id)
    elif message.text == '8d':
        markup = telebot.types.ReplyKeyboardMarkup(one_time_keyboard=True)
        markup.add('Kemar', 'SAMREC-2500R', 'D1')
        msg = bot.reply_to(message, 'Оберіть за яким сетом створювати ефект. \n<i>(Експерементуйте, оберіть один, а потім спробуйте інший)</i> \n<b>Поділіться враженням написавши відгук сюди <a href="https://t.me/spdownloader">Channel</a></b>', parse_mode="HTML", reply_markup=markup)
        bot.register_next_step_handler(msg, process_8d_step_1, file_id)
    elif message.text == 'SpeedUp':
        msg = bot.reply_to(message, 'Введіть число від 1 до 2:')
        bot.register_next_step_handler(msg, process_speed_up_step, file_id)
    else:
        bot.reply_to(message, 'Неправильний вибір. Спробуйте знову.')

def process_8d_step_1(message, file_id):
    if message.text == "Kemar":
        bot.reply_to(message, 'Зачекайте! Обробка триває... Це може зайняти деякий час.')
        process_8d_step_kemar(message, file_id)
    elif message.text == "D1":
        bot.reply_to(message, 'Зачекайте! Обробка триває... Це може зайняти деякий час.')
        process_8d_step_D1(message, file_id)
    elif message.text == "SAMREC-2500R":
        bot.reply_to(message, 'Зачекайте! Обробка триває... Це може зайняти деякий час.')
        process_8d_step_SAMREC(message, file_id)

def process_8d_step_SAMREC(message, file_id):
    global input_file, output_file2, output_file
    try:
        file_info = bot.get_file(file_id)
        file_path = file_info.file_path

        # Отримуємо оригінальне ім'я файлу та розширення
        original_filename = file_path.split("/")[-1]
        extension = original_filename.split(".")[-1]

        input_file = f"downloads/{file_id}.{extension}"
        output_file = f"downloads/{file_id}_processed.wav"
        output_file2 = f"downloads/{file_id}-processed.{extension}"

        # Завантажуємо файл
        downloaded_file = bot.download_file(file_path)
        with open(input_file, "wb") as f:
            f.write(downloaded_file)

        convert_to_wav(input_file, output_file)

        apply_8d_effect_base(output_file, output_file2)

        # 🔥 Перевіряємо, чи FFmpeg успішно створив вихідний файл
        if not os.path.exists(output_file2):
            bot.reply_to(message, "❌ Помилка: оброблений файл не створено!")
            return

        # Відправляємо оброблений файл
        with open(output_file2, "rb") as f:
            bot.send_audio(message.chat.id, f, reply_to_message_id=message.message_id)

        os.remove(input_file)
        os.remove(output_file)
        os.remove(output_file2)
    except Exception as e:
        bot.reply_to(message, f"❌ Помилка: {str(e)}")

        os.remove(input_file)
        os.remove(output_file)
        os.remove(output_file2)
        if os.path.exists('downloads/track.wav'):
            os.remove(input_file)
        if os.path.exists('downloads/temp.wav'):
            os.remove(input_file)

def process_8d_step_D1(message, file_id):
    try:
        file_info = bot.get_file(file_id)
        file_path = file_info.file_path

        # Отримуємо оригінальне ім'я файлу та розширення
        original_filename = file_path.split("/")[-1]
        extension = original_filename.split(".")[-1]

        input_file = f"downloads/{file_id}.{extension}"
        output_file = f"downloads/{file_id}_processed.wav"
        output_file2 = f"downloads/{file_id}-processed1.wav"
        output_file3 = f"downloads/{file_id}-processed.m4a"

        # Завантажуємо файл
        downloaded_file = bot.download_file(file_path)
        with open(input_file, "wb") as f:
            f.write(downloaded_file)

        convert_to_wav(input_file, output_file)

        apply_8d_effect_D1(output_file, output_file2)

        convert_to_m4a(output_file2, output_file3)

        # 🔥 Перевіряємо, чи FFmpeg успішно створив вихідний файл
        if not os.path.exists(output_file3):
            bot.reply_to(message, "❌ Помилка: оброблений файл не створено!")
            return

        # Відправляємо оброблений файл
        with open(output_file3, "rb") as f:
            bot.send_audio(message.chat.id, f, reply_to_message_id=message.message_id)

        os.remove(input_file)
        os.remove(output_file)
        os.remove(output_file2)
        os.remove(output_file3)
    except Exception as e:
        bot.reply_to(message, f"❌ Помилка: {str(e)}")

        os.remove(input_file)
        os.remove(output_file)
        os.remove(output_file2)
        if os.path.exists('downloads/track.wav'):
            os.remove(input_file)
        if os.path.exists('downloads/temp.wav'):
            os.remove(input_file)

def process_8d_step_kemar(message, file_id):
    try:
        file_info = bot.get_file(file_id)
        file_path = file_info.file_path

        # Отримуємо оригінальне ім'я файлу та розширення
        original_filename = file_path.split("/")[-1]
        extension = original_filename.split(".")[-1]

        input_file = f"downloads/{file_id}.{extension}"
        output_file = f"downloads/{file_id}_processed.wav"
        output_file2 = f"downloads/{file_id}-processed.{extension}"

        # Завантажуємо файл
        downloaded_file = bot.download_file(file_path)
        with open(input_file, "wb") as f:
            f.write(downloaded_file)

        convert_to_wav(input_file, output_file)

        apply_8d_effect_SOFA(output_file, output_file2)

        # 🔥 Перевіряємо, чи FFmpeg успішно створив вихідний файл
        if not os.path.exists(output_file2):
            bot.reply_to(message, "❌ Помилка: оброблений файл не створено!")
            return

        # Відправляємо оброблений файл
        with open(output_file2, "rb") as f:
            bot.send_audio(message.chat.id, f, reply_to_message_id=message.message_id)

        os.remove(input_file)
        os.remove(output_file)
        os.remove(output_file2)
    except Exception as e:
        bot.reply_to(message, f"❌ Помилка: {str(e)}")

        os.remove(input_file)
        os.remove(output_file)
        os.remove(output_file2)
        if os.path.exists('downloads/track.wav'):
            os.remove(input_file)
        if os.path.exists('downloads/temp.wav'):
            os.remove(input_file)


def process_reverb_step(message, file_id):
    global input_file, output_file2, output_file
    try:
        file_info = bot.get_file(file_id)
        file_path = file_info.file_path

        # Отримуємо оригінальне ім'я файлу та розширення
        original_filename = file_path.split("/")[-1]
        extension = original_filename.split(".")[-1]

        input_file = f"downloads/{file_id}.{extension}"
        output_file = f"downloads/{file_id}_processed.wav"
        output_file2 = f"downloads/{file_id}-processed.{extension}"

        # Завантажуємо файл
        downloaded_file = bot.download_file(file_path)
        with open(input_file, "wb") as f:
            f.write(downloaded_file)

        convert_to_wav(input_file, output_file)

        apply_reverb(output_file, output_file2)

        # Відправляємо оброблений файл
        with open(output_file2, "rb") as f:
            bot.send_audio(message.chat.id, f, reply_to_message_id=message.message_id)

        os.remove(input_file)
        os.remove(output_file)
        os.remove(output_file2)
    except Exception as e:
        bot.reply_to(message, f"❌ Помилка: {str(e)}")

        os.remove(input_file)
        os.remove(output_file)
        os.remove(output_file2)
        if os.path.exists('downloads/track.wav'):
            os.remove(input_file)
        if os.path.exists('downloads/temp.wav'):
            os.remove(input_file)

def process_dance_eq_step(message, file_id):
    global input_file, output_file, output_file2
    try:
        file_info = bot.get_file(file_id)
        file_path = file_info.file_path

        # Отримуємо оригінальне ім'я файлу та розширення
        original_filename = file_path.split("/")[-1]
        extension = original_filename.split(".")[-1]

        input_file = f"downloads/{file_id}.{extension}"
        output_file = f"downloads/{file_id}_processed.wav"
        output_file2 = f"downloads/track.wav"

        # Завантажуємо файл
        downloaded_file = bot.download_file(file_path)
        with open(input_file, "wb") as f:
            f.write(downloaded_file)

        convert_to_wav(input_file, output_file)

        dance_eq(output_file, output_file2)

        # Відправляємо оброблений файл
        with open(output_file2, "rb") as f:
            bot.send_audio(message.chat.id, f, reply_to_message_id=message.message_id)

        os.remove(input_file)
        os.remove(output_file)
        os.remove(output_file2)
    except Exception as e:
        bot.reply_to(message, f"❌ Помилка: {str(e)}")

        os.remove(input_file)
        os.remove(output_file)
        os.remove(output_file2)
        if os.path.exists('downloads/track.wav'):
            os.remove(input_file)
        if os.path.exists('downloads/temp.wav'):
            os.remove(input_file)

def process_speed_up_step(message, file_id):
    bot.reply_to(message, 'Зачекайте! Обробка триває...')
    try:
        speed = float(message.text)
        if 1 <= speed <= 2:
            file_info = bot.get_file(file_id)
            file_path = file_info.file_path

            # Отримуємо оригінальне ім'я файлу та розширення
            original_filename = file_path.split("/")[-1]
            extension = original_filename.split(".")[-1]

            input_file = f"downloads/{file_id}.{extension}"
            output_file = f"downloads/{file_id}_processed.{extension}"

            # Завантажуємо файл
            downloaded_file = bot.download_file(file_path)
            with open(input_file, "wb") as f:
                f.write(downloaded_file)

            speed_up_audio(input_file, output_file, speed)

            bot.reply_to(message, f'Швидкість збільшено на {speed} рази.')

            # Відправляємо оброблений файл
            with open(output_file, "rb") as f:
                bot.send_audio(message.chat.id, f, reply_to_message_id=message.message_id)

            os.remove(input_file)
            os.remove(output_file)
        else:
            bot.reply_to(message, 'Число повинно бути між 1 і 2. Спробуйте знову.')
    except ValueError:
        bot.reply_to(message, 'Неправильне число. Спробуйте знову.')


# --- ФУНКЦІЯ ДЛЯ ОБРОБКИ ---

import os
import soundfile as sf


def load_hrir_set(directory):
    """
    Завантажує HRIR дані з папки.
    Очікується, що файли мають назви типу:
      L-000.wav, L-005.wav, ..., L-355.wav для лівого каналу,
      R-000.wav, R-005.wav, ..., R-355.wav для правого каналу.
    """
    hrir_database = {}

    # Проходимо по файлах у папці
    for filename in os.listdir(directory):
        if filename.endswith(".wav") and filename.startswith("L-"):
            # Витягуємо кут з назви файлу, наприклад, "L-010.wav" -> "010"
            angle_str = filename.split('-')[1].split('.')[0]
            angle = int(angle_str)

            left_filepath = os.path.join(directory, filename)
            right_filename = f"R-{angle_str}.wav"
            right_filepath = os.path.join(directory, right_filename)

            if os.path.exists(right_filepath):
                hrir_left, sr_left = sf.read(left_filepath)
                hrir_right, sr_right = sf.read(right_filepath)

                if sr_left != sr_right:
                    print(f"Sample rates не співпадають для кута {angle}.")

                hrir_database[angle] = (hrir_left, hrir_right)
            else:
                print(f"Правий файл {right_filename} не знайдено для кута {angle}.")

    return hrir_database

directory = "D:\SAMREC-2500R-HRIR-Dataset"
hrir_database = load_hrir_set(directory)
print("Завантажено HRIR для кутів:", sorted(hrir_database.keys()))


def get_hrir(angle, hrir_database):
    """
    Повертає пару HRIR для заданого кута.
    Якщо точне значення не знайдено, вибирає найближчий кут.
    """
    available_angles = sorted(hrir_database.keys())
    closest_angle = min(available_angles, key=lambda a: abs(a - angle))
    return hrir_database[closest_angle]

def apply_8d_effect_base(input_file, output_file):
    """
    Створює 8D ефект за допомогою HRIR-датасету.
    Аудіо розбивається на блоки, для кожного блоку визначається кут обертання,
    після чого блок згортатиметься з відповідними імпульсними відповідями для лівого і правого вух.
    Результат збирається методом overlap-add і зберігається як стерео файл.
    """
    # Завантаження вхідного аудіо
    audio, sr = sf.read(input_file)
    # Якщо аудіо має більше одного каналу, перетворимо в моно (середнє значення)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    # Параметри блокування: 0.1 сек на блок
    block_duration = 0.1  # сек
    block_size = int(sr * block_duration)
    num_blocks = int(np.ceil(len(audio) / block_size))

    # Визначаємо довжину HRIR (припускаємо, що для всіх кутів вона однакова)
    sample_angle = next(iter(hrir_database))
    hrir_length = len(hrir_database[sample_angle][0])

    # Обчислюємо розмір вихідного сигналу (overlap-add: кожен блок додається з зміщенням block_size)
    output_length = num_blocks * block_size + hrir_length - 1
    output = np.zeros((output_length, 2))  # 2 канали: лівий та правий

    # Параметри динамічного обертання: наприклад, один повний оберт (360°) за 10 секунд
    rotation_period = 10.0  # секунд

    # Обробка кожного блоку
    for i in range(num_blocks):
        start_idx = i * block_size
        block = audio[start_idx: start_idx + block_size]
        # Визначаємо час центру блоку (в секундах)
        block_time = (start_idx + len(block) / 2) / sr
        # Обчислюємо кут: робимо циклічний оберт від 0 до 360 градусів
        angle = (360 * (block_time / rotation_period)) % 360

        # Отримуємо пару HRIR для заданого (або найближчого) кута
        hrir_left, hrir_right = get_hrir(angle, hrir_database)

        # Згортка блоку з HRIR для кожного каналу
        conv_left = signal.convolve(block, hrir_left, mode='full')
        conv_right = signal.convolve(block, hrir_right, mode='full')
        conv_length = len(conv_left)  # має дорівнювати len(block) + hrir_length - 1

        # Overlap-add: додаємо згорнутий блок у вихідний сигнал з відповідним зміщенням
        output[start_idx:start_idx + conv_length, 0] += conv_left
        output[start_idx:start_idx + conv_length, 1] += conv_right

    # Нормалізація фінального сигналу для уникнення обрізання (clipping)
    max_val = np.max(np.abs(output))
    if max_val > 0:
        output = output / max_val

    # Записуємо вихідний аудіо файл
    sf.write(output_file, output, sr)

def speed_up_audio(input_path, output_path, speed=1.5):
    """Функція для зміни швидкості та пітчу аудіо з підсиленням низьких частот"""
    command = f'ffmpeg -i "{input_path}" -filter:a "asetrate=44100*{speed},aresample=44100,bass=g=5" -vn "{output_path}"'
    subprocess.run(command, shell=True)

def dance_eq(input_path, output_path):
    """Застосовує Dance EQ через FFmpeg"""
    command = f'ffmpeg -i "{input_path}" -filter:a "bass=g=12" -vn "{output_path}"'
    subprocess.run(command, shell=True)

def get_hrir_sofa(azimuth, elevation, sofa_file, hrir_data):
    """Отримання HRIR для заданого азимуту та елевації."""
    # Пошук найближчої відповідності по кутах
    pos = sofa_file.getVariableValue('SourcePosition')
    distances = np.sqrt((pos[:, 0] - azimuth)**2 + (pos[:, 1] - elevation)**2)
    idx = np.argmin(distances)
    hrir_left = hrir_data[idx, 0, :]
    hrir_right = hrir_data[idx, 1, :]
    return hrir_left, hrir_right

def apply_8d_effect_SOFA(input_file, output_file):
    # Вкажіть абсолютний шлях до SOFA файлу
    file_path = 'D:/NBurc/Python/tarantas_spdownloader_bot/mit_kemar_large_pinna.sofa'
    sofa_file = sofa.SOFAFile(file_path, 'r')
    # Отримання даних HRIR та відповідної інформації
    hrir_data = sofa_file.getDataIR()
    hrir_sampling_rate = sofa_file.getSamplingRate()
    audio, sr = sf.read(input_file)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    block_duration = 0.1
    block_size = int(sr * block_duration)
    num_blocks = int(np.ceil(len(audio) / block_size))

    output_length = num_blocks * block_size + hrir_data.shape[2] - 1
    output = np.zeros((output_length, 2))

    rotation_period = 10.0

    for i in range(num_blocks):
        start_idx = i * block_size
        block = audio[start_idx: start_idx + block_size]
        block_time = (start_idx + len(block) / 2) / sr
        angle = (360 * (block_time / rotation_period)) % 360
        hrir_left, hrir_right = get_hrir_sofa(angle, 0, sofa_file, hrir_data)

        conv_left = signal.convolve(block, hrir_left, mode='full')
        conv_right = signal.convolve(block, hrir_right, mode='full')
        conv_length = len(conv_left)

        output[start_idx:start_idx + conv_length, 0] += conv_left
        output[start_idx:start_idx + conv_length, 1] += conv_right

    max_val = np.max(np.abs(output))
    if max_val > 0:
        output = output / max_val

    sf.write(output_file, output, sr)

def apply_8d_effect_D1(input_file, output_file):
    # Вкажіть абсолютний шлях до SOFA файлу
    file_path = r'D:\NBurc\Python\tarantas_spdownloader_bot\D1_96K_24bit_512tap_FIR_SOFA.sofa'
    sofa_file = sofa.SOFAFile(file_path, 'r')
    # Отримання даних HRIR та відповідної інформації
    hrir_data = sofa_file.getDataIR()
    hrir_sampling_rate = sofa_file.getSamplingRate()
    audio, sr = sf.read(input_file)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    block_duration = 0.1
    block_size = int(sr * block_duration)
    num_blocks = int(np.ceil(len(audio) / block_size))

    output_length = num_blocks * block_size + hrir_data.shape[2] - 1
    output = np.zeros((output_length, 2))

    rotation_period = 10.0

    for i in range(num_blocks):
        start_idx = i * block_size
        block = audio[start_idx: start_idx + block_size]
        block_time = (start_idx + len(block) / 2) / sr
        angle = (360 * (block_time / rotation_period)) % 360
        hrir_left, hrir_right = get_hrir_sofa(angle, 0, sofa_file, hrir_data)

        conv_left = signal.convolve(block, hrir_left, mode='full')
        conv_right = signal.convolve(block, hrir_right, mode='full')
        conv_length = len(conv_left)

        output[start_idx:start_idx + conv_length, 0] += conv_left
        output[start_idx:start_idx + conv_length, 1] += conv_right

    max_val = np.max(np.abs(output))
    if max_val > 0:
        output = output / max_val


    sf.write(output_file, output, sr)



def apply_reverb(input_file, output_file):
    """Додає реверберацію (луна, об'ємний ефект)"""
    subprocess.run([
        'ffmpeg', '-i',
        input_file,
        '-af', 'aecho=0.8:0.88:60:0.4, stereotools=mlev=1', output_file, '-y'
    ], check=True)

@bot.callback_query_handler(func=lambda call: True)
@check_user_access
def handle_callback(call):
    """Оновлений обробник callback-запитів з підтримкою YouTube"""
    try:
        user_id = call.from_user.id

        # Обробка вибору формату
        if call.data.startswith("format_"):
            audio_format = call.data.split("_")[1]
            user_audio_format[user_id] = audio_format

            # Показуємо меню вибору способу доставки
            markup = create_delivery_method_keyboard()
            bot.edit_message_text(
                f"Формат {audio_format.upper()} вибрано. Як ви хочете отримати файли?",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
            return
        if call.data == "speedup":
            bot.send_message(call.message.chat.id, "Надішли файл та обери опцію.")
        if call.data == "bassboost":
            bot.send_message(call.message.chat.id, "Надішли файл та обери опцію.")
        # Обробка вибору способу доставки
        if call.data.startswith("delivery_"):
            handle_delivery_method(call)
            return

        # Отримуємо треки користувача
        tracks = user_tracks.get(user_id)
        if not tracks:
            bot.answer_callback_query(call.id, "Помилка: треки не знайдено")
            return

        if call.data.startswith("track_"):
            track_index = int(call.data.split('_')[1])
            track = tracks[track_index]

            # Завантажуємо трек в залежності від джерела (YouTube чи Spotify)
            if user_delivery_method.get(user_id) == "zip":
                handle_zip_download(call, [track])
            else:
                if track.get('is_youtube'):
                    download_youtube_track(track, call.message.chat.id, user_audio_format)
                else:
                    download_and_send_track(track, call.message.chat.id, user_audio_format)

        elif call.data == "download_all":
            if user_delivery_method.get(user_id) == "zip":
                handle_zip_download(call, tracks)
            else:
                handle_single_download(call, tracks)

    except Exception as e:
        logger.exception(f"Error in callback handler: {str(e)}")
        bot.send_message(call.message.chat.id, f"Виникла помилка: {str(e)}")


def handle_delivery_method(call):
    """Обробка вибору способу надсилання"""
    user_id = call.from_user.id
    tracks = user_tracks.get(user_id)

    if call.data == "delivery_single":
        user_delivery_method[user_id] = "single"
        markup = create_tracks_keyboard(tracks)
        bot.edit_message_text(
            "Обери треки для завантаження:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

    elif call.data == "delivery_zip":
        user_delivery_method[user_id] = "zip"
        markup = create_tracks_keyboard(tracks)
        bot.edit_message_text(
            "Обери треки для завантаження в ZIP архів:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )


def handle_single_download(call, tracks):
    """Обробка завантаження по одному файлу"""
    if call.data == "download_all":
        bot.edit_message_text(
            "Починаю завантаження всіх треків...",
            call.message.chat.id,
            call.message.message_id
        )

        total_tracks = len(tracks)
        for i, track in enumerate(tracks, 1):
            try:
                bot.send_message(
                    call.message.chat.id,
                    f"Завантаження треку {i}/{total_tracks}: {track['artist']} - {track['name']}"
                )
                download_and_send_track(track, call.message.chat.id, user_audio_format)
            except Exception as e:
                bot.send_message(
                    call.message.chat.id,
                    f"❌ Помилка при завантаженні {track['artist']} - {track['name']}: {str(e)}"
                )

        bot.send_message(
            call.message.chat.id,
            f"✅ Завантаження всіх треків завершено!"
        )

    else:
        track_index = int(call.data.split('_')[1])
        track = tracks[track_index]
        download_and_send_track(track, call.message.chat.id, user_audio_format)


def send_large_file(bot, chat_id, file_path, caption=None, max_retries=3):
    """
    Надсилає великий файл через Telegram API з підтримкою повторних спроб
    та обробкою помилок.
    """
    for attempt in range(max_retries):
        try:
            with open(file_path, 'rb') as file:
                return bot.send_document(
                    chat_id=chat_id,
                    document=file,
                    caption=caption,
                    allow_sending_without_reply=True,
                    timeout=300  # Використовуємо єдиний параметр timeout
                )
        except Exception as e:
            if attempt == max_retries - 1:  # Якщо це була остання спроба
                raise e
            logger.warning(f"Attempt {attempt + 1} failed: {str(e)}. Retrying...")
            time.sleep(5)  # Чекаємо перед повторною спробою


def handle_zip_download(call, tracks):
    """Оновлена функція для створення ZIP архіву з підтримкою YouTube"""
    global user_id, track_name
    try:
        user_id = call.from_user.id
        temp_folder = create_temp_folder(user_id)
        user_temp_folders[user_id] = temp_folder

        status_message = bot.edit_message_text(
            "Підготовка до створення ZIP архіву...",
            call.message.chat.id,
            call.message.message_id
        )

        total_tracks = len(tracks)
        downloaded_files = []

        for i, track in enumerate(tracks, 1):
            try:
                if track.get('is_youtube'):
                    # Для YouTube треківє


                    track_name = f"{track['author']} - {track['title']}"
                else:
                    # Для Spotify треків
                    track_name = f"{track['artist']} - {track['name']}"

                bot.edit_message_text(
                    f"⏳ Завантаження треку {i}/{total_tracks}:\n"
                    f"{track_name}\n"
                    f"Загальний прогрес: [{i}/{total_tracks}]",
                    call.message.chat.id,
                    status_message.message_id
                )

                progress = DownloadProgress(bot, call.message.chat.id, track_name)
                progress.send_initial_message()

                if track.get('is_youtube'):
                    output_path = download_youtube_track_for_zip(
                        temp_folder,
                        track,
                        progress,
                        user_audio_format
                    )
                else:
                    output_path = download_track_for_zip(
                        temp_folder,
                        track,
                        progress,
                        user_audio_format
                    )

                if output_path and os.path.exists(output_path):
                    downloaded_files.append(output_path)

            except Exception as e:
                bot.send_message(
                    call.message.chat.id,
                    f"❌ Помилка при завантаженні {track_name}: {str(e)}"
                )

        # Решта коду для створення та надсилання ZIP архіву залишається без змін
        if downloaded_files:
            bot.edit_message_text(
                "📦 Створення ZIP архіву...",
                call.message.chat.id,
                status_message.message_id
            )

            chunks = split_file(downloaded_files, temp_folder, 49 * 1024 * 1024)

            for i, chunk_path in enumerate(chunks, 1):
                try:
                    bot.edit_message_text(
                        f"📤 Надсилання частини {i}/{len(chunks)}...",
                        call.message.chat.id,
                        status_message.message_id
                    )

                    with open(chunk_path, 'rb') as file:
                        bot.send_document(
                            chat_id=call.message.chat.id,
                            document=file,
                            caption=f"Частина {i} з {len(chunks)}"
                        )

                    os.remove(chunk_path)

                except Exception as e:
                    bot.send_message(
                        call.message.chat.id,
                        f"❌ Помилка при надсиланні частини {i}: {str(e)}"
                    )

        # Очищення
        cleanup_temp_folder(temp_folder)
        del user_temp_folders[user_id]

    except Exception as e:
        logger.exception(f"Error in ZIP download: {str(e)}")
        bot.send_message(
            call.message.chat.id,
            f"Виникла помилка при створенні ZIP архіву: {str(e)}"
        )
        if user_id in user_temp_folders:
            cleanup_temp_folder(user_temp_folders[user_id])
            del user_temp_folders[user_id]

# Запуск бота
def main():
    # Створюємо папку для тимчасових файлів
    os.makedirs("temp", exist_ok=True)
    logging.info("Bot started")
    bot.infinity_polling()

if __name__ == "__main__":
    main()
