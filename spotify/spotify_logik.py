import re
import eyed3
from pydub import AudioSegment
from syncedlyrics import search
import logging
import os
import yt_dlp
import transliterate
import requests
from spotipy import Spotify
from spotipy.oauth2 import SpotifyClientCredentials
from ytmusicapi import YTMusic
from outh_data import token, CLIENT_ID, CLIENT_SECRET
import  telebot
bot = telebot.TeleBot(token)
sp = Spotify(auth_manager=SpotifyClientCredentials(client_id=CLIENT_ID, client_secret=CLIENT_SECRET))
ytmusic = YTMusic()

# Константи
# Отримуємо шлях до файлу spotify_logik.py
current_file_path = os.path.abspath(__file__)

# Визначаємо кореневу папку проекту (папка tarantas_spdownloader_bot)
root_dir = os.path.dirname(os.path.dirname(current_file_path))

# Шлях до папки Music
OUTPUT_DIR = os.path.join(root_dir, "Music")

print(OUTPUT_DIR)

os.makedirs(OUTPUT_DIR, exist_ok=True)

def is_spotify_playlist_url(url):
    """Перевіряє, чи є URL плейлистом Spotify"""
    spotify_pattern = r'https?://(?:open\.)?spotify\.com/playlist/[a-zA-Z0-9]+'
    return bool(re.match(spotify_pattern, url))


def get_playlist_id(url):
    """Витягує ID плейлиста з URL"""
    match = re.search(r'playlist/([a-zA-Z0-9]+)', url)
    return match.group(1) if match else None


def get_tracks_from_playlist(playlist_url):
    """Отримує треки з плейлиста Spotify"""
    playlist_id = get_playlist_id(playlist_url)
    if not playlist_id:
        raise ValueError("Невірний формат URL плейлиста")

    results = sp.playlist_items(playlist_id)
    tracks = []

    for item in results["items"]:
        if item["track"]:  # Перевіряємо, чи трек існує
            track = item["track"]
            tracks.append({
                "name": track["name"],
                "artist": track["artists"][0]["name"],
            })

    return tracks

def get_cover_image(track_id):
    track = sp.track(track_id)
    images = track['album']['images']
    if images:
        return images[0]['url']  # Найбільше зображення

    return None


def download_cover_image(track_id):
    """
    Завантажує обкладинку треку з Spotify за його ID.
    """
    cover_url = get_cover_image(track_id)
    if not cover_url:
        return None

    response = requests.get(cover_url)
    if response.status_code == 200:
        return response.content  # Повертаємо як bytes
    return None


def add_metadata_to_mp3(mp3_file_path, cover_image_data, lyrics, artist_name, synced_lyrics=None):
    audio_file = eyed3.load(mp3_file_path)
    AudioSegment.converter = "tools/FFMpeg/ffmpeg.exe"
    AudioSegment.ffprobe = "tools/FFMpeg/ffprobe.exe"
    if audio_file.tag is None:
        audio_file.initTag()

    try:
        audio = AudioSegment.from_file(mp3_file_path)
    except Exception as e:
        logging.error(f"Error processing file {mp3_file_path}: {e}")
        raise
    audio_length = len(audio) / 1000  # у секундах

    # Якщо є синхронізовані лірики, отримуємо їх тривалість
    subtitles_length = None
    if synced_lyrics:
        timestamps = re.findall(r"\[(\d{2}):(\d{2})\.\d{2}\]", synced_lyrics)
        if timestamps:
            minutes, seconds = map(int, timestamps[-1])
            subtitles_length = minutes * 60 + seconds

    # Перевіряємо тривалість
    if subtitles_length is not None:
        if abs(audio_length - subtitles_length) > 1:  # допускаємо відхилення в 1 секунду
            print("Довжини аудіо і субтитрів не співпадають. Вбудовування скасоване.")
            return

    # Вбудовуємо метадані
    if cover_image_data:
        audio_file.tag.images.set(3, cover_image_data, "image/jpeg")
    if lyrics:
        audio_file.tag.lyrics.set(lyrics)
    if artist_name:
        audio_file.tag.artist = artist_name

    audio_file.tag.save()
    print("Метадані успішно додано.")

def search_track(track: str):
    query = f"{track}"
    results = ytmusic.search(query=query, filter="songs")
    if results:
        return results[0]['videoId']  # Повертаємо videoId першого результату
    return None

def get_synced_lyrics(track_name, artist_name):
    if isinstance(track_name, dict):
        search_term = f"{track_name['artist']} {track_name['name']}"
    else:
        search_term = f"{artist_name} {track_name}"
    try:
        lyrics = search(search_term, enhanced=True, synced_only=True, providers=['genius', 'musixmatch', 'lrclib'])
        if lyrics:
            pattern = r"<\d{2}:\d{2}\.\d{2}>"
            lyrics = re.sub(pattern, "", lyrics)
            print(f"Synced lyrics found: {lyrics}")

            return lyrics
        else:
            lyrics = search(search_term, enhanced=True, providers=['genius', 'musixmatch', 'lrclib'])
            pattern = r"<\d{2}:\d{2}\.\d{2}>"
            lyrics = re.sub(pattern, "", lyrics)
            print(f"Lyrics found: {lyrics}")

            return lyrics
    except Exception as e:
        logging.error(f"Error getting lyrics: {e}")
        return None  # Повертаємо None замість підняття помилки
    return None


class DownloadProgress:
    def __init__(self, bot, chat_id, track_name):
        self.bot = bot
        self.chat_id = chat_id
        self.track_name = track_name
        self.status_message = None
        self.progress = 0

    def send_initial_message(self):
        """Надсилає початкове повідомлення про завантаження"""
        self.status_message = self.bot.send_message(
            self.chat_id,
            f"Починаю завантаження '{self.track_name}' 🎵\n[□□□□□□□□□□] 0%"
        )

    def update_progress(self, progress):
        """Оновлює повідомлення з прогресом"""
        if self.status_message and progress != self.progress:
            self.progress = progress
            filled_blocks = int(progress / 10)
            empty_blocks = 10 - filled_blocks
            progress_bar = f"[{'■' * filled_blocks}{'□' * empty_blocks}] {progress}%"

            try:
                self.bot.edit_message_text(
                    f"Завантаження '{self.track_name}' 🎵\n{progress_bar}",
                    self.chat_id,
                    self.status_message.message_id
                )
            except telebot.apihelper.ApiTelegramException:
                # Ігноруємо помилку, якщо повідомлення не змінилося
                pass

    def complete(self):
        """Позначає завантаження як завершене"""
        if self.status_message:
            self.bot.edit_message_text(
                f"✅ Трек '{self.track_name}' успішно завантажено!",
                self.chat_id,
                self.status_message.message_id
            )


def download_and_send_track(track, chat_id):
    """Завантажує та надсилає трек з індикацією прогресу"""
    global track_name, progress
    try:
        track_name = f"{track['artist']} - {track['name']}"
        progress = DownloadProgress(bot, chat_id, track_name)
        progress.send_initial_message()

        safe_track_name = transliterate.translit(track_name, reversed=True)
        file_path = f"{OUTPUT_DIR}/{safe_track_name}.mp3"

        # Пошук треку
        progress.update_progress(10)
        video_id = search_track(track_name)
        if not video_id:
            raise Exception("Трек не знайдено на YouTube Music")

        progress.update_progress(20)

        # Налаштування для yt-dlp з колбеком прогресу
        def ydl_progress_hook(d):
            if d['status'] == 'downloading':
                # Прогрес завантаження від 20% до 60%
                try:
                    downloaded = d.get('downloaded_bytes', 0)
                    total = d.get('total_bytes', 0) or d.get('total_bytes_estimate', 0)
                    if total:
                        p = int(20 + (downloaded / total * 40))
                        progress.update_progress(p)
                except:
                    pass

        ydl_opts = {
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            'ffmpeg_location': 'tools/FFMpeg/',
            "outtmpl": f"{OUTPUT_DIR}/{safe_track_name}.%(ext)s",
            "progress_hooks": [ydl_progress_hook],
            'verbose': True,

            'keepvideo': False,

        }

        # Завантаження
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])

        progress.update_progress(60)

        # Додавання метаданих
        search_query = f"{track['artist']} {track['name']}"  # Формуємо правильний пошуковий запит
        result = sp.search(search_query, limit=1)
        if result['tracks']['items']:
            track_id = result['tracks']['items'][0]['id']
            artist_name = result['tracks']['items'][0]['artists'][0]['name']
            cover_image_data = download_cover_image(track_id)
            lyrics = get_synced_lyrics(track['name'], track['artist'])

            if cover_image_data or lyrics:
                add_metadata_to_mp3(file_path, cover_image_data, lyrics, artist_name)

                progress.update_progress(90)

            # Надсилання файлу
            with open(file_path, 'rb') as audio:
                bot.send_audio(
                    chat_id=chat_id,
                    audio=audio,
                    title=track['name'],
                    performer=track['artist']
                )

            progress.update_progress(100)
            progress.complete()

            # Видалення файлу після надсилання
            os.remove(file_path)

    except Exception as e:
        logging.error(f"Error downloading track {track_name}: {str(e)}")
        if progress.status_message:
            bot.edit_message_text(
                f"❌ Помилка при завантаженні '{track_name}': {str(e)}",
                chat_id,
                progress.status_message.message_id
            )
        raise
