import re
import time
import zipfile

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import logging
from spotify.spotify_logik import is_spotify_playlist_url, get_tracks_from_playlist, download_and_send_track, bot, create_zip_file, download_track_for_zip, DownloadProgress
import os
import transliterate
from datetime import datetime
import sys

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
user_tracks = {}
user_delivery_method = {}  # Зберігання вибраного способу надсилання
user_temp_folders = {}  # Зберігання шляхів до тимчасових папок


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
        track_name = f"{track['artist']} - {track['name']}"
        markup.add(InlineKeyboardButton(
            text=track_name,
            callback_data=f"track_{i}"
        ))

    markup.add(InlineKeyboardButton("Завантажити все", callback_data="download_all"))
    return markup


@bot.message_handler(commands=['start'])
def start_message(message):
    """Обробник команди /start"""
    bot.reply_to(message, "Привіт! Надішли мені посилання на плейлист Spotify")


@bot.message_handler(func=lambda message: is_spotify_playlist_url(message.text))
def handle_playlist_url(message):
    """Обробник URL плейлиста"""
    try:
        # Отримуємо треки
        tracks = get_tracks_from_playlist(message.text)
        user_tracks[message.from_user.id] = tracks

        # Питаємо про спосіб надсилання
        markup = create_delivery_method_keyboard()
        bot.reply_to(
            message,
            "Як ви хочете отримати файли?",
            reply_markup=markup
        )

    except Exception as e:
        logger.exception(f"Error handling playlist: {str(e)}")
        bot.reply_to(message, f"Виникла помилка при обробці плейлиста: {str(e)}")


@bot.message_handler(func=lambda message: True)
def handle_text(message):
    """Обробник всіх інших повідомлень"""
    if message.text.lower() == 'spotify':
        bot.reply_to(message, "Чудово! Тепер надішли мені посилання на плейлист Spotify")
    else:
        bot.reply_to(message, "Надішли мені посилання на плейлист Spotify або напиши 'spotify'")


def create_temp_folder(user_id):
    """Створює тимчасову папку для користувача"""
    folder_name = f"temp_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    path = os.path.join("temp", folder_name)
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


@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    """Обробник всіх callback запитів"""
    try:
        user_id = call.from_user.id

        # Обробка вибору способу надсилання
        if call.data.startswith("delivery_"):
            handle_delivery_method(call)
            return

        # Обробка вибору треків
        tracks = user_tracks.get(user_id)
        if not tracks:
            bot.answer_callback_query(call.id, "Помилка: треки не знайдено")
            return
        if call.data.startswith("track_") & (user_delivery_method.get(user_id) == "zip"):
            track_index = int(call.data.split('_')[1])
            tracks = [user_tracks[user_id][track_index]]  # Обираємо лише один трек
            handle_zip_download(call, tracks)
        else:


            delivery_method = user_delivery_method.get(user_id)
            if delivery_method == "zip":
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
                download_and_send_track(track, call.message.chat.id)
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
        download_and_send_track(track, call.message.chat.id)


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

def safe_transliterate(text):
    """
    Безпечна транслітерація тексту з обробкою спеціальних символів
    """
    try:
        # Замінюємо спеціальні символи на безпечні
        safe_text = re.sub(r'[&]', 'and', text)  # Заміна & на and
        safe_text = re.sub(r'[^\w\s-]', '', safe_text)  # Видалення інших спеціальних символів
        # Транслітерація з обробкою помилок
        try:
            result = transliterate.translit(safe_text, reversed=True)
        except Exception:
            # Якщо транслітерація не вдалася, використовуємо оригінальний текст
            result = safe_text
        return result
    except Exception as e:
        logger.error(f"Error in safe_transliterate: {str(e)}")
        # Повертаємо безпечну версію оригінального тексту
        return re.sub(r'[^\w\s-]', '', text)  # Чекаємо перед повторною спробою


def split_file(tracks, temp_folder, max_size=6 * 1024 * 1024):
    """
    Розділяє список треків на кілька ZIP-архівів, щоб кожен не перевищував заданий розмір.
    :param tracks: Список шляхів до файлів треків.
    :param temp_folder: Шлях до тимчасової папки для збереження ZIP-файлів.
    :param max_size: Максимальний розмір одного ZIP-архіву в байтах.
    :return: Список шляхів до створених ZIP-архівів.
    """
    zip_files = []  # Список для збереження шляхів до архівів
    current_zip_size = 0  # Поточний розмір архіву
    current_zip_index = 1  # Лічильник для назв архівів
    current_zip_path = os.path.join(temp_folder, f"playlist_part{current_zip_index}.zip")

    # Відкриваємо перший ZIP-файл
    zip_file = zipfile.ZipFile(current_zip_path, 'w', zipfile.ZIP_DEFLATED)

    for track in tracks:
        track_size = os.path.getsize(track)  # Отримуємо розмір файлу треку

        # Перевіряємо, чи влізе трек у поточний архів
        if current_zip_size + track_size > max_size:
            # Закриваємо поточний ZIP-архів
            zip_file.close()
            zip_files.append(current_zip_path)

            # Створюємо новий архів
            current_zip_index += 1
            current_zip_path = os.path.join(temp_folder, f"playlist_part{current_zip_index}.zip")
            zip_file = zipfile.ZipFile(current_zip_path, 'w', zipfile.ZIP_DEFLATED)
            current_zip_size = 0  # Скидаємо розмір архіву

        # Додаємо трек до поточного архіву
        zip_file.write(track, arcname=os.path.basename(track))
        current_zip_size += track_size

    # Закриваємо останній архів і додаємо його до списку
    zip_file.close()
    zip_files.append(current_zip_path)

    return zip_files


def handle_zip_download(call, tracks):
    """Оновлена функція для створення та надсилання ZIP архіву"""
    try:
        user_id = call.from_user.id

        # Створюємо тимчасову папку
        temp_folder = create_temp_folder(user_id)
        user_temp_folders[user_id] = temp_folder

        status_message = bot.edit_message_text(
            "Підготовка до створення ZIP архіву...",
            call.message.chat.id,
            call.message.message_id
        )

        total_tracks = len(tracks)
        downloaded_tracks = []

        # Завантаження треків
        for i, track in enumerate(tracks, 1):
            try:
                bot.edit_message_text(
                    f"⏳ Завантаження треку {i}/{total_tracks}:\n"
                    f"{track['artist']} - {track['name']}\n"
                    f"Загальний прогрес: [{i}/{total_tracks}]",
                    call.message.chat.id,
                    status_message.message_id
                )

                safe_track_name = re.sub("&","and",f"{track['artist']} - {track['name']}")

                file_path = os.path.join(temp_folder, f"{safe_track_name}.mp3")

                # Завантажуємо трек
                progress = DownloadProgress(
                    bot,
                    call.message.chat.id,
                    f"{track['artist']} - {track['name']}"
                )
                progress.send_initial_message()

                download_track_for_zip(temp_folder, track, file_path, progress)
                downloaded_tracks.append(file_path)

            except Exception as e:
                bot.send_message(
                    call.message.chat.id,
                    f"❌ Помилка при завантаженні {track['artist']} - {track['name']}: {str(e)}"
                )

        if downloaded_tracks:
            # Створюємо ZIP архів
            bot.edit_message_text(
                "📦 Створення ZIP архіву...",
                call.message.chat.id,
                status_message.message_id
            )


            chunks = split_file(downloaded_tracks, temp_folder)

            # Надсилаємо кожну частину
            for i, chunk_path in enumerate(chunks, 1):
                try:
                    bot.edit_message_text(
                        f"📤 Надсилання частини {i}/{len(chunks)}...",
                        call.message.chat.id,
                        status_message.message_id
                    )

                    send_large_file(
                        bot,
                        call.message.chat.id,
                        chunk_path,
                        caption=f"Частина {i} з {len(chunks)} - "
                                f"Завантажено {len(downloaded_tracks)}/{total_tracks} треків"
                    )

                    # Видаляємо частину після надсилання
                    os.remove(chunk_path)

                except Exception as e:
                    bot.send_message(
                        call.message.chat.id,
                        f"❌ Помилка при надсиланні частини {i}: {str(e)}"
                    )


    except Exception as e:
        logger.exception(f"Error in ZIP download: {str(e)}")
        bot.send_message(
            call.message.chat.id,
            f"Виникла помилка при створенні ZIP архіву: {str(e)}"
        )

        # Очищення у випадку помилки
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