import io
import logging

import yadisk
from django.utils import timezone
from django.core.files.base import ContentFile
from django.core.files import File as DjangoFile

from django_whisper_pipeline import celery_app
from django_whisper_pipeline.logging_handlers import get_task_logger
from django_whisper_pipeline.settings import YA_DISK_TOKEN
from transcriber.models import Task, TaskHistory
from filer.models import Folder, File
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)
MODEL = None

def get_whisper_model():
    global MODEL
    if MODEL is None:
        logger.info("[get_whisper_model] Загружаем модель Whisper впервые...")
        MODEL = WhisperModel("/app/models")  # или "small", если хочешь быстрее
        logger.info("[get_whisper_model] Модель Whisper успешно загружена")
    return MODEL

@celery_app.task
def download_from_yadisk_task(task_id):
    logger = get_task_logger(task_id)
    logger.info(f"[download_from_yadisk_task] Запуск задачи для task_id={task_id}")
    task = Task.objects.get(id=task_id)
    old_status = task.status

    task.status = Task.Status.PROCESSING_FILLED_FILES
    task.save(update_fields=["status"])
    logger.debug(f"[download_from_yadisk_task] Статус задачи {task_id} изменён на PROCESSING_FILLED_FILES")

    try:
        ya = yadisk.YaDisk(token=YA_DISK_TOKEN)
        folder_url = task.ya_disk_path.strip()
        logger.info(f"[download_from_yadisk_task] Проверяем доступность ссылки: {folder_url}")

        if not ya.exists(folder_url, public_key=folder_url):
            raise ValueError(f"Ссылка {folder_url} недоступна")

        # создаём или берём папку в Filer
        if not task.folder:
            folder_name = f"task_{task.id}"
            filer_folder, _ = Folder.objects.get_or_create(name=folder_name)
            task.folder = filer_folder
            task.save(update_fields=["folder"])
            logger.info(f"[download_from_yadisk_task] Создана новая папка Filer: {folder_name}")
        else:
            filer_folder = task.folder
            logger.debug(f"[download_from_yadisk_task] Используем существующую папку Filer: {filer_folder.name}")

        # перебираем файлы на Я.Диске
        logger.info(f"[download_from_yadisk_task] Начинаем загрузку файлов из {folder_url}")
        for item in ya.listdir(folder_url):
            if item["type"] != "file":
                logger.debug(f"[download_from_yadisk_task] Пропускаем элемент (не файл): {item['name']}")
                continue

            filename = item["name"]
            file_path = item["path"]
            logger.info(f"[download_from_yadisk_task] Скачиваем файл: {filename}")

            file_like = io.BytesIO()
            ya.download(file_path, file_like)

            file_like.seek(0)
            content = ContentFile(file_like.read(), name=filename)
            DjangoFile_obj = DjangoFile(content, name=filename)

            File.objects.create(
                original_filename=filename,
                file=DjangoFile_obj,
                folder=filer_folder,
                owner=None,
            )
            logger.debug(f"[download_from_yadisk_task] Файл {filename} сохранён в Filer")

        task.status = Task.Status.NEW
        task.last_error = ""
        logger.info(f"[download_from_yadisk_task] Все файлы успешно загружены для задачи {task_id}")

    except Exception as e:
        logger.exception(f"[download_from_yadisk_task] Ошибка при скачивании файлов: {e}")
        task.status = Task.Status.ERROR
        task.last_error = str(e)

    finally:
        task.status = old_status
        task.save(update_fields=["status", "last_error"])
        logger.info(f"[download_from_yadisk_task] Завершено. Статус возвращён в {old_status}")


@celery_app.task
def run_ready_tasks():
    logger.info("[run_ready_tasks] Проверяем готовые задачи")
    now = timezone.now()
    ready_tasks = Task.objects.filter(status__in=[Task.Status.NEW, Task.Status.DONE])
    logger.debug(f"[run_ready_tasks] Найдено задач для проверки: {ready_tasks.count()}")

    for task in ready_tasks:
        if task.is_ready_to_run(now):
            logger.info(f"[run_ready_tasks] Задача {task.id} готова к запуску — запускаем transcribe_task()")
            transcribe_task(task.id)
        else:
            logger.debug(f"[run_ready_tasks] Задача {task.id} пока не готова")


@celery_app.task
def delete_all_files(task_id):
    logger = get_task_logger(task_id)
    logger.info(f"[delete_all_files] Удаление файлов для задачи {task_id}")
    try:
        task = Task.objects.get(id=task_id)
        if not task.folder:
            logger.debug(f"[delete_all_files] У задачи {task_id} нет связанной папки — пропуск")
            return

        if not task.delete_after_send:
            logger.debug("[delete_all_files] Удаление отключено (delete_after_send=False) — пропуск")
            return

        files_qs = File.objects.filter(folder=task.folder)
        logger.info(f"[delete_all_files] Найдено файлов для удаления: {files_qs.count()}")
        for f in files_qs:
            try:
                f.file.delete(save=False)
                f.delete()
                logger.debug(f"[delete_all_files] Удалён файл {f.original_filename}")
            except Exception as e:
                logger.warning(f"[delete_all_files] Не удалось удалить файл {f.id} ({f.original_filename}): {e}")

        # task.folder.delete()

    except Task.DoesNotExist:
        logger.warning(f"[delete_all_files] Задача с id={task_id} не найдена")


@celery_app.task
def transcribe_task(task_id):
    logger = get_task_logger(task_id)
    logger.info(f"[transcribe_task] Запуск транскрипции для задачи {task_id}")
    try:
        task = Task.objects.get(id=task_id)
        logger.debug(f"[transcribe_task] Статус задачи: {task.status}")

        if task.status in [Task.Status.PROCESSING, Task.Status.PROCESSING_FILLED_FILES, Task.Status.ERROR]:
            logger.warning(f"[transcribe_task] Задача {task_id} в недопустимом статусе для транскрипции — пропуск")
            return

        task.status = Task.Status.PROCESSING
        task.save(update_fields=["status"])
        logger.info(f"[transcribe_task] Статус задачи {task_id} изменён на PROCESSING")

        if task.task_type == task.TaskType.PERIODIC:
            logger.info(f"[transcribe_task] У задачи {task_id} тип PERIODIC — очищаем старые файлы")
            delete_all_files.delay(task_id)

        logger.info(f"[transcribe_task] Загружаем файлы с Я.Диска для задачи {task_id}")
        download_from_yadisk_task(task_id)
        task.refresh_from_db()

        if not task.folder:
            raise ValueError("У задачи нет папки с файлами")

        files_qs = File.objects.filter(folder=task.folder)
        logger.info(f"[transcribe_task] Найдено файлов для транскрипции: {files_qs.count()}")
        if not files_qs.exists():
            raise ValueError("В папке нет файлов для обработки")

        model = get_whisper_model()
        logger.info("[transcribe_task] Модель Whisper загружена")

        full_transcript = []
        for f in files_qs:
            audio_path = f.file.path
            logger.info(f"[transcribe_task] Транскрибируем файл: {audio_path}")
            segments, info = model.transcribe(audio_path, language="ru")
            text = " ".join([segment.text for segment in segments])
            full_transcript.append(text)
            logger.debug(f"[transcribe_task] Файл {f.original_filename} транскрибирован, длина текста: {len(text)}")

        final_text = "\n\n".join(full_transcript)
        logger.info(f"[transcribe_task] Транскрипция завершена. Общая длина текста: {len(final_text)}")

        transcript_file = File(
            original_filename=f"task_{task.id}_transcript.txt",
            # folder=task.folder
        )
        transcript_file.file.save(
            f"task_{task.id}_transcript.txt",
            ContentFile(final_text)
        )
        transcript_file.save()
        logger.info(f"[transcribe_task] Файл результата сохранён: {transcript_file.file.name}")

        task.result_file = transcript_file
        task.status = Task.Status.DONE
        task.last_error = ""
        task.save(update_fields=["status", "result_file", "last_error"])
        logger.info(f"[transcribe_task] Задача {task_id} завершена успешно (DONE)")

        if task.task_type == task.TaskType.ONE_TIME:
            logger.info("[transcribe_task] Тип задачи ONE_TIME — удаляем исходные файлы")
            delete_all_files(task_id)

        TaskHistory.objects.create(
            task=task,
            payload={
                "status": task.status,
                "last_error": task.last_error,
                "files_processed": files_qs.count(),
                "result_file": task.result_file.file.name if task.result_file else None,
            }
        )
        logger.info("[transcribe_task] Запись в историю добавлена")

    except Exception as e:
        logger.exception(f"[transcribe_task] Ошибка при транскрипции задачи {task_id}: {e}")
        task.status = Task.Status.ERROR
        task.last_error = str(e)
        task.save(update_fields=["status", "last_error"])

        TaskHistory.objects.create(
            task=task,
            payload={
                "status": task.status,
                "last_error": task.last_error,
            }
        )

    finally:
        task.last_run = timezone.now()
        task.save(update_fields=["last_run"])
        logger.info(f"[transcribe_task] Завершено выполнение задачи {task_id}. Обновлён last_run")
