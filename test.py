import librosa
import numpy as np
import matplotlib.pyplot as plt
from pydub import AudioSegment
import pyrubberband as pyrb
from scipy.signal import butter, lfilter
import os


def load_audio(file_path):
    """Завантажує аудіофайл"""
    return AudioSegment.from_file(file_path)


def speed_up(audio, speed_factor=1.2):
    """Прискорює аудіо на вказаний фактор"""
    # Конвертуємо pydub AudioSegment в numpy array
    samples = np.array(audio.get_array_of_samples())

    # Використовуємо pyrubberband для зміни швидкості без зміни висоти тону
    samples_stretched = pyrb.time_stretch(samples.astype(np.float32), audio.frame_rate, speed_factor)

    # Конвертуємо назад у формат pydub
    modified_audio = audio._spawn(np.int16(samples_stretched))

    return modified_audio


def enhance_bass(audio, bass_boost=5):
    """Підсилює баси на вказану кількість децибел"""
    # Низькочастотний фільтр для виділення басів
    bass_audio = audio.low_pass_filter(200)

    # Підсилюємо баси
    enhanced_bass = bass_audio + bass_boost
    enhanced_bass = enhanced_bass.set_frame_rate(audio.frame_rate).set_channels(audio.channels).set_sample_width(
        audio.sample_width)
    enhanced_bass = enhanced_bass[:len(audio)]
    # Змішуємо з оригінальним аудіо
    return audio.overlay(enhanced_bass)



def add_fonk_bass(audio, pattern_file, volume=-5):
    """Додає фонк-баси з шаблонного файлу"""
    fonk_pattern = AudioSegment.from_file(pattern_file)

    # Аналізуємо біт оригінального треку щоб синхронізувати фонк-баси
    y, sr = librosa.load(audio.export(format="wav"), sr=None)
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beats, sr=sr)

    # Створюємо новий трек з фонк-басами на кожному біті
    result = audio
    for beat_time in beat_times:
        position_ms = int(beat_time * 1000)
        if position_ms < len(audio):
            result = result.overlay(fonk_pattern, position=position_ms, gain=volume)

    return result


def stereo_panning_on_transitions(audio, sections, transition_duration=500):
    """
    Створює ефект панорамування між лівим і правим каналами на переходах

    sections - список кортежів (start_ms, end_ms, is_chorus)
    transition_duration - тривалість переходу в мілісекундах
    """
    result = audio

    for i in range(len(sections) - 1):
        current_section = sections[i]
        next_section = sections[i + 1]

        # Якщо є перехід між куплетом і приспівом
        if current_section[2] != next_section[2]:
            transition_start = next_section[0] - transition_duration

            # Вирізаємо частину аудіо для переходу
            transition_audio = audio[transition_start:next_section[0]]

            # Створюємо панорамування (від лівого до правого або навпаки)
            if current_section[2]:  # Якщо поточна секція - приспів
                panned_transition = stereo_pan(transition_audio, start=-1.0, end=1.0)
            else:
                panned_transition = stereo_pan(transition_audio, start=1.0, end=-1.0)

            # Замінюємо оригінальний перехід
            result = result[:transition_start] + panned_transition + result[next_section[0]:]

    return result


def stereo_pan(audio, start=-1.0, end=1.0):
    """
    Створює ефект панорамування від start до end

    start/end: -1.0 - повністю лівий канал, 1.0 - повністю правий канал
    """
    frames = len(audio)
    result = AudioSegment.silent(duration=len(audio), frame_rate=audio.frame_rate)

    # Створюємо копії для лівого і правого каналів
    left = audio.pan(-1)
    right = audio.pan(1)

    # Поступово змінюємо баланс каналів
    step_size = 20  # мс
    for i in range(0, frames, step_size):
        if i + step_size > frames:
            step_size = frames - i

        # Розраховуємо поточний баланс
        progress = i / frames
        current_pan = start + (end - start) * progress

        # Змішуємо канали відповідно до поточного балансу
        if current_pan < 0:  # Більше лівого каналу
            left_volume = 1.0
            right_volume = 1.0 + current_pan
        else:  # Більше правого каналу
            left_volume = 1.0 - current_pan
            right_volume = 1.0

        segment = left[i:i + step_size].apply_gain(left_volume) + right[i:i + step_size].apply_gain(right_volume)
        result = result[:i] + segment + result[i + step_size:]

    return result


def create_remix(input_file, output_file, fonk_pattern_file, sections,
                 speed_factor=1.2, bass_boost=5, fonk_volume=-5):
    """
    Створює ремікс з вхідного файлу

    sections - список кортежів (start_ms, end_ms, is_chorus) для визначення секцій
    """
    # Завантажуємо аудіо
    audio = load_audio(input_file)

    # Застосовуємо ефекти
    audio = speed_up(audio, speed_factor)
    audio = enhance_bass(audio, bass_boost)
    audio = stereo_panning_on_transitions(audio, sections)

    # Зберігаємо результат
    audio.export(output_file, format="mp3")
    print(f"Ремікс збережено у файлі {output_file}")


def detect_sections(audio_file, plot=True):
    """
    Автоматично визначає секції аудіо (куплет/приспів)
    Повертає список секцій у форматі [(start_time, end_time, is_chorus), ...]
    """
    # Завантажуємо аудіо
    y, sr = librosa.load(audio_file, sr=None)

    # Тривалість у секундах
    duration = librosa.get_duration(y=y, sr=sr)

    # Визначаємо хромаграму (представлення гармонічного змісту)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)

    # Визначаємо RMS енергію (гучність)
    rms = librosa.feature.rms(y=y)[0]

    # Визначаємо спектральний контраст
    contrast = librosa.feature.spectral_contrast(y=y, sr=sr)

    # Визначаємо темп і біти
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beats, sr=sr)

    # Знаходимо сегменти на основі зміни структурних елементів
    # Використовуємо алгоритм кластеризації для пошуку схожих сегментів
    boundary_frames = librosa.segment.agglomerative(chroma, n_segments=8)
    boundary_times = librosa.frames_to_time(boundary_frames, sr=sr)

    # Аналізуємо кожен сегмент, щоб визначити, чи це приспів
    sections = []
    for i in range(len(boundary_times) - 1):
        start_time = boundary_times[i]
        end_time = boundary_times[i + 1]

        # Конвертуємо час в семпли
        start_sample = librosa.time_to_samples(start_time, sr=sr)
        end_sample = librosa.time_to_samples(end_time, sr=sr)

        # Отримуємо середнє значення RMS енергії в сегменті
        segment_rms = np.mean(rms[start_sample:end_sample]) if start_sample < len(rms) and end_sample <= len(rms) else 0

        # Обчислюємо деякі характеристики для сегменту
        # Приспіви зазвичай гучніші та мають більшу енергію
        segment_contrast = np.mean(contrast[:, start_sample:end_sample], axis=1) if start_sample < contrast.shape[
            1] and end_sample <= contrast.shape[1] else np.zeros(contrast.shape[0])

        # Хороший евристичний підхід: приспіви зазвичай мають більшу RMS енергію
        # Але це не завжди так - можуть бути тихі приспіви і гучні куплети
        is_chorus = segment_rms > np.mean(rms) * 1.1  # 10% вище середньої гучності

        # Додаємо результат у мілісекундах
        sections.append((int(start_time * 1000), int(end_time * 1000), bool(is_chorus)))

    # Виведення результатів
    if plot:
        plt.figure(figsize=(12, 6))

        # Відображаємо аудіо-хвилю
        times = np.linspace(0, duration, len(y))
        plt.plot(times, y, color='gray', alpha=0.5)

        # Відображаємо секції
        for start, end, is_chorus in sections:
            start_sec = start / 1000
            end_sec = end / 1000
            color = 'red' if is_chorus else 'blue'
            label = 'Приспів' if is_chorus else 'Куплет'
            plt.axvspan(start_sec, end_sec, color=color, alpha=0.3,
                        label=label if label not in plt.gca().get_legend_handles_labels()[1] else "")

        # Додаємо легенду (тільки одну для кожного типу)
        handles, labels = plt.gca().get_legend_handles_labels()
        by_label = dict(zip(labels, handles))
        plt.legend(by_label.values(), by_label.keys())

        plt.title('Визначення секцій аудіо')
        plt.xlabel('Час (секунди)')
        plt.ylabel('Амплітуда')
        plt.tight_layout()
        plt.savefig('audio_sections.png')
        plt.close()

        print(f"Графік збережено як 'audio_sections.png'")

    # Виведення знайдених секцій
    print("Знайдені секції:")
    for i, (start, end, is_chorus) in enumerate(sections):
        section_type = "Приспів" if is_chorus else "Куплет"
        start_sec = start / 1000
        end_sec = end / 1000
        duration_sec = end_sec - start_sec
        print(f"{i + 1}. {section_type}: {start_sec:.1f}-{end_sec:.1f} с (тривалість: {duration_sec:.1f} с)")

    return sections


def refine_sections_with_repetition(audio_file, sections):
    """
    Вдосконалення визначення приспівів на основі повторень
    Приспіви часто повторюються в пісні
    """
    # Завантажуємо аудіо
    y, sr = librosa.load(audio_file, sr=None)

    # Обчислюємо хромаграму для кожної секції
    section_chromas = []
    for start, end, _ in sections:
        start_sample = librosa.time_to_samples(start / 1000, sr=sr)
        end_sample = librosa.time_to_samples(end / 1000, sr=sr)

        if start_sample >= len(y) or end_sample > len(y):
            continue

        section_y = y[start_sample:end_sample]
        chroma = librosa.feature.chroma_cqt(y=section_y, sr=sr)
        section_chromas.append(np.mean(chroma, axis=1))

    # Знаходимо схожі секції
    similar_sections = []
    for i in range(len(section_chromas)):
        similar = []
        for j in range(len(section_chromas)):
            if i != j:
                # Обчислюємо косинусну схожість між хромаграмами
                similarity = np.dot(section_chromas[i], section_chromas[j]) / (
                        np.linalg.norm(section_chromas[i]) * np.linalg.norm(section_chromas[j]))

                if similarity > 0.9:  # Високий поріг схожості
                    similar.append(j)

        similar_sections.append(similar)

    # Секції, які повторюються, швидше за все є приспівом
    refined_sections = []
    for i, (start, end, is_chorus) in enumerate(sections):
        # Якщо ця секція має багато схожих секцій, позначаємо як приспів
        if i < len(similar_sections) and len(similar_sections[i]) >= 1:
            is_chorus = True

        refined_sections.append((start, end, is_chorus))

    return refined_sections


# Приклад використання
if __name__ == "__main__":
    # Визначте секції треку: (початок_мс, кінець_мс, це_приспів)
    track_sections = [
        (0, 55000, False),  # Вступ і перший куплет
        (55000, 71000, True),  # Перший приспів
        (71000, 110000, False),  # Другий куплет
        (110000, 126000, True),  # Другий приспів
        (126000, None, False)  # Кінець пісні (None означає кінець файлу)
    ]

    create_remix(
        input_file="D:/AyuGram Desktop/Amirchik - Карта тройка.mp3",
        output_file="remix.mp3",
        fonk_pattern_file="fonk_bass.wav",
        sections=track_sections,
        speed_factor=1.2,
        bass_boost=6,
        fonk_volume=-5
    )
