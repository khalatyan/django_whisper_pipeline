import io
import logging
from contextlib import contextmanager

import yadisk
from django.core.cache import cache
from django.db.models.query_utils import Q
from django.utils import timezone
from django.core.files.base import ContentFile
from django.core.files import File as DjangoFile
from django.db import transaction

from django_whisper_pipeline import celery_app
from django_whisper_pipeline.logging_handlers import get_task_logger
from django_whisper_pipeline.settings import YA_DISK_TOKEN
from transcriber.models import Task, TaskFile
from filer.models import Folder, File
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)
MODEL = None

@contextmanager
def single_task_lock(lock_name: str, timeout: int = 300):
    """
    Контекстный менеджер для блокировки выполнения задачи.
    lock_name — уникальное имя блокировки.
    timeout — время жизни блокировки в секундах.
    """
    lock = cache.lock(lock_name, timeout=timeout)
    acquired = lock.acquire(blocking=False)
    try:
        if not acquired:
            yield False  # уже выполняется другая задача
        else:
            yield True
    finally:
        if acquired:
            lock.release()


def get_whisper_model():
    global MODEL
    if MODEL is None:
        logger.info("[get_whisper_model] Загружаем модель Whisper впервые...")
        # MODEL = WhisperModel("/app/models", device="cpu", compute_type="int8")  # или "small", если хочешь быстрее
        MODEL = WhisperModel("small")  # или "small", если хочешь быстрее
        logger.info("[get_whisper_model] Модель Whisper успешно загружена")
    return MODEL

def download_from_yadisk_task(task_id):
    logger = get_task_logger(task_id)
    logger.info(f"[download_from_yadisk_task] Запуск задачи для task_id={task_id}")
    task = Task.objects.get(id=task_id)
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

        task.last_error = ""
        logger.info(f"[download_from_yadisk_task] Все файлы успешно загружены для задачи {task_id}")

    except Exception as e:
        logger.exception(f"[download_from_yadisk_task] Ошибка при скачивании файлов: {e}")
        task.status = Task.Status.ERROR
        task.last_error = str(e)

    finally:
        task.save(update_fields=["status", "last_error"])
        logger.info("[download_from_yadisk_task] Завершено.")


def fill_task_files(task_id):
    task = Task.objects.get(id=task_id)
    for f in File.objects.filter(folder=task.folder):
        TaskFile.objects.get_or_create(
            task=task,
            filer_file=f,
            defaults={"status": TaskFile.Status.NEW}
        )


@celery_app.task
def run_ready_tasks():
    lock_name = "run_ready_tasks_global_lock"

    with single_task_lock(lock_name, timeout=1200) as acquired:
        if not acquired:
            logger.info("[run_ready_tasks] Пропуск — другая задача уже выполняется")
            return

        logger.info("[run_ready_tasks] Проверяем готовые задачи")
        now = timezone.now()
        ready_tasks = Task.objects.filter(
            Q(status=Task.Status.NEW) |
            Q(Q(task_type=Task.TaskType.PERIODIC) & Q(status=Task.Status.DONE))
        )
        logger.debug(f"[run_ready_tasks] Найдено задач для проверки: {ready_tasks.count()}")

        for task in ready_tasks:
            if task.is_ready_to_run(now):
                with transaction.atomic():
                    task.status = Task.Status.PROCESSING
                    for file in File.objects.filter(folder=task.folder):
                        file.delete(save=False)
                    for file in task.files.all():
                        file.filer_file.delete(save=False)
                    if task.source_type == task.SourceType.YADISK:
                        download_from_yadisk_task(task.id)
                    fill_task_files(task.id)

                    task.save(update_fields=["status"])

        processed_tasks = Task.objects.filter(status=Task.Status.PROCESSING)
        for task in processed_tasks:
            if not task.files.exclude(status=Task.Status.DONE).exists():
                task.status = Task.Status.DONE
                task.save(update_fields=["status"])


@celery_app.task
def process_task_file():
    lock_name = "process_task_file_global_lock"

    with single_task_lock(lock_name, timeout=1200) as acquired:
        if not acquired:
            logger.info("[process_task_file] Пропуск — другая задача уже выполняется")
            return

        task_file = (
            TaskFile.objects
            .filter(task__status=Task.Status.PROCESSING, status=TaskFile.Status.NEW)
            .first()
        )

        if not task_file:
            logger.info("[process_task_file] Нет новых файлов для обработки")
            return

        logger.info(f"[process_task_file] Начинаем обработку файла {task_file.id}")
        task_file.status = TaskFile.Status.PROCESSING
        task_file.save(update_fields=["status"])

        model = get_whisper_model()

        try:
            segments, info = model.transcribe(task_file.filer_file.file.path, language="ru")
            text = " ".join([seg.text for seg in segments])

            task_file.result_text = text
            task_file.status = TaskFile.Status.DONE
            task_file.error = ""
            task_file.save(update_fields=["result_text", "status", "error"])

            # Удаляем файл с CPU, но не из Filer-базы
            task_file.filer_file.file.delete(save=False)

            logger.info(f"[process_task_file] Файл {task_file.id} успешно обработан")

        except Exception as e:
            logger.exception(f"[process_task_file] Ошибка при обработке файла {task_file.id}: {e}")
            task_file.status = TaskFile.Status.ERROR
            task_file.error = str(e)
            task_file.save(update_fields=["status", "error"])