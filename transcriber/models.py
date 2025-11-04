from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
import uuid
from filer.fields.folder import FilerFolderField
from filer.fields.file import FilerFileField

class Task(models.Model):
    class SourceType(models.TextChoices):
        LOCAL = "LOCAL", "Загрузить вручную"
        YADISK = "YADISK", "Из Яндекс.Диска"

    class TaskType(models.TextChoices):
        ONE_TIME = "ONE_TIME", "Одноразовый"
        PERIODIC = "PERIODIC", "Периодический"

    class Status(models.TextChoices):
        NEW = "NEW", "Новый"
        PROCESSING = "PROCESSING", "В обработке"
        PROCESSING_FILLED_FILES = "PROCESSING_FILLED_FILES", "В обработке файлов из диска"
        DONE = "DONE", "Обработан"
        ERROR = "ERROR", "Ошибка"

    class IntervalType(models.TextChoices):
        MINUTES = "MINUTES", "Минуты"
        HOURS = "HOURS", "Часы"
        DAYS = "DAYS", "Дни"

    id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False, verbose_name="ID задачи"
    )
    name = models.CharField(max_length=255, verbose_name="Название задачи")

    source_type = models.CharField(
        max_length=20, choices=SourceType.choices, default=SourceType.LOCAL,
        help_text="Откуда загружаем файлы", verbose_name="Источник файлов"
    )
    task_type = models.CharField(
        max_length=20, choices=TaskType.choices, default=TaskType.ONE_TIME,
        help_text="Тип запуска задачи", verbose_name="Тип запуска задачи"
    )
    ya_disk_path = models.CharField(
        max_length=1024, blank=True,
        help_text="Путь или ссылка на Яндекс.Диск, если выбран этот источник",
        verbose_name="Ссылка на Яндекс.Диск"
    )
    folder = FilerFolderField(
        verbose_name='Папка в Filer',
        on_delete=models.CASCADE,
        default=None,
        null=True,
        blank=True
    )
    result_file = FilerFileField(
        verbose_name="Файл с результатом",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="task_result_file"
    )

    interval = models.PositiveIntegerField(verbose_name="Интервал", default=0)
    interval_type = models.CharField(max_length=10, choices=IntervalType.choices, default=IntervalType.DAYS)

    run_once_at = models.DateTimeField(
        help_text="Если запуск один раз", verbose_name="Дата однократного запуска"
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата обновления")
    status = models.CharField(
        max_length=32, choices=Status.choices, default=Status.NEW,
        verbose_name="Статус"
    )
    last_error = models.TextField(blank=True, verbose_name="Последняя ошибка")
    last_run = models.DateTimeField(null=True, blank=True, verbose_name="Последний запуск")

    archive_after_send = models.BooleanField(default=True, verbose_name="Архивировать после отправки")
    delete_after_send = models.BooleanField(default=True, verbose_name="Удалять после отправки")
    meta = models.JSONField(default=dict, blank=True, verbose_name="Метаданные")

    class Meta:
        verbose_name = "Задача"
        verbose_name_plural = "Задачи"

    def __str__(self):
        return self.name

    def next_run_time(self):
        """Следующее время запуска задачи."""
        if not self.run_once_at:
            return None

        # Одноразовая задача
        if self.task_type == self.TaskType.ONE_TIME:
            return self.run_once_at

        # Проверка интервала
        if not self.interval or self.interval <= 0:
            return self.run_once_at

        # Интервал в timedelta
        if self.interval_type == self.IntervalType.MINUTES:
            delta = timedelta(minutes=self.interval)
        elif self.interval_type == self.IntervalType.HOURS:
            delta = timedelta(hours=self.interval)
        elif self.interval_type == self.IntervalType.DAYS:
            delta = timedelta(days=self.interval)
        else:
            delta = timedelta(days=1)

        now = timezone.now()

        # Если ещё не было запуска, первый запуск = run_once_at
        if not self.last_run:
            return max(self.run_once_at, now)

        # Периодический запуск от last_run
        next_run = self.last_run + delta
        return next_run

    def is_ready_to_run(self, now=None):
        now = now or timezone.now()

        # Если задача уже в обработке, запускать нельзя
        if self.status in [self.Status.PROCESSING, self.Status.PROCESSING_FILLED_FILES]:
            return False

        if self.task_type == self.TaskType.ONE_TIME:
            return (self.last_run is None) and (self.run_once_at <= now)

        next_time = self.next_run_time()
        if not next_time:
            return False

        # Можно запускать, если сейчас уже >= следующего цикла
        return now >= next_time

    def clean(self):
        super().clean()

        if self.task_type == self.TaskType.PERIODIC:
            if not self.interval or self.interval <= 0:
                raise ValidationError({"interval": "Для периодической задачи нужно указать интервал."})


class TaskHistory(models.Model):
    task = models.ForeignKey(
        Task, on_delete=models.CASCADE, related_name="history", verbose_name="Задача"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания записи")
    payload = models.JSONField(verbose_name="Данные выполнения")

    class Meta:
        verbose_name = "История задачи"
        verbose_name_plural = "История задач"

    def __str__(self):
        return f"History {self.task_id} @ {self.created_at.isoformat()}"

class TaskLog(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="logs")
    level = models.CharField(max_length=20)
    message = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)
    extra = models.JSONField(blank=True, null=True)  # можно сохранять stacktrace или дополнительные данные

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Лог задачи"
        verbose_name_plural = "Логи задач"

    def __str__(self):
        return f"[{self.level}] {self.task.name} - {self.created_at}"