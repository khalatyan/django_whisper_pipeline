from django.conf import settings
from django.contrib import admin
from django.urls.base import reverse
from django.utils.html import format_html
from .models import Task, TaskHistory, TaskLog


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "task_type",
        "source_type",
        "status",
        "next_run_display",
        "last_run",
        "created_at",
    )
    list_filter = ("task_type", "status", "source_type")
    search_fields = ("name", "ya_disk_path")
    readonly_fields = (
        "last_run",
        "created_at",
        "updated_at",
        "result_file_display",
        "folder_link",
    )
    actions = ["run_task_now"]

    fieldsets = (
        ("Основное", {"fields": ("name", "task_type", "source_type")}),
        ("Источник данных", {"fields": ("ya_disk_path", "folder", "folder_link")}),
        ("Запуск задачи", {"fields": ("run_once_at", "interval", "interval_type")}),
        ("Результат и статус", {"fields": ("result_file_display", "status", "last_error", "last_run")}),
        ("Служебное", {"fields": ("created_at", "updated_at", "meta")}),
    )

    def folder_link(self, obj):
        """Ссылка для открытия папки в django-filer (просмотр файлов)."""
        if not obj.folder:
            return "-"
        try:
            url = reverse("admin:filer-directory_listing", args=[obj.folder.id])
            return format_html('<a href="{}" target="_blank">Открыть папку с файлами</a>', url)
        except Exception:
            return obj.folder.name
    folder_link.short_description = "Папка с файлами"

    def next_run_display(self, obj):
        if obj.task_type == obj.TaskType.PERIODIC:
            return obj.next_run_time()
        elif obj.task_type == obj.TaskType.ONE_TIME:
            return obj.run_once_at
        return "-"
    next_run_display.short_description = "Следующий запуск"

    def result_file_display(self, obj):
        if obj.result_file and obj.result_file.file:
            url = f"{settings.MEDIA_URL}{obj.result_file.file.name}"
            return format_html('<a href="{}" download>Скачать результат</a>', url)
        return "-"

    result_file_display.short_description = "Файл результата"

@admin.register(TaskHistory)
class TaskHistoryAdmin(admin.ModelAdmin):
    list_display = ("task", "created_at", "status_display")
    readonly_fields = ("created_at", "payload")

    def status_display(self, obj):
        # Если в payload есть статус выполнения
        return obj.payload.get("status", "-")
    status_display.short_description = "Статус"

@admin.register(TaskLog)
class TaskLogAdmin(admin.ModelAdmin):
    list_display = ("task", "level", "created_at", "message")
    list_filter = ("task", "level", "created_at")
    search_fields = ("message", "task__name")