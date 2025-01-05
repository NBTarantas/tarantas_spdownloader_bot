from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import logging
from spotify.spotify_logik import is_spotify_playlist_url, get_tracks_from_playlist, download_and_send_track, bot

# Налаштування логування
logging.basicConfig(level=logging.INFO)

# Словник для зберігання треків користувачів
user_tracks = {}

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
        # Отримуємо та зберігаємо треки
        tracks = get_tracks_from_playlist(message.text)
        user_tracks[message.from_user.id] = tracks

        # Створюємо клавіатуру
        markup = create_tracks_keyboard(tracks)

        bot.reply_to(message, "Обери треки для завантаження:", reply_markup=markup)

    except Exception as e:
        logging.error(f"Error handling playlist: {str(e)}")
        bot.reply_to(message, f"Виникла помилка при обробці плейлиста: {str(e)}")


@bot.message_handler(func=lambda message: True)
def handle_text(message):
    """Обробник всіх інших повідомлень"""
    if message.text.lower() == 'spotify':
        bot.reply_to(message, "Чудово! Тепер надішли мені посилання на плейлист Spotify")
    else:
        bot.reply_to(message, "Надішли мені посилання на плейлист Spotify або напиши 'spotify'")


@bot.callback_query_handler(func=lambda call: True)
def handle_track_selection(call):
    """Обробник вибору треків"""
    try:
        user_id = call.from_user.id
        tracks = user_tracks.get(user_id)

        if not tracks:
            bot.answer_callback_query(call.id, "Помилка: треки не знайдено")
            return

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
                        f"Завантаження треку {i}/{total_tracks}"
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

    except Exception as e:
        logging.error(f"Error in track selection: {str(e)}")
        bot.send_message(call.message.chat.id, f"Виникла помилка: {str(e)}")






# Запуск бота
def main():
    logging.info("Bot started")
    bot.infinity_polling()


if __name__ == "__main__":
    main()