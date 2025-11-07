
from django.contrib import admin
from django.http.response import HttpResponse
from django.urls.base import reverse
from django.urls.conf import path
from django.utils.html import format_html

from .models import Task, TaskHistory, TaskLog, TaskFile

@admin.register(TaskFile)
class TaskFileAdmin(admin.ModelAdmin):
    pass

class TaskFileInline(admin.TabularInline):
    model = TaskFile
    extra = 0

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
        "download_results_button",
    )
    list_filter = ("task_type", "status", "source_type")
    search_fields = ("name", "ya_disk_path")
    readonly_fields = (
        "last_run",
        "created_at",
        "updated_at",
        "folder_link",
    )
    actions = ["run_task_now"]

    fieldsets = (
        ("Основное", {"fields": ("name", "task_type", "source_type")}),
        ("Источник данных", {"fields": ("ya_disk_path", "folder", "folder_link")}),
        ("Запуск задачи", {"fields": ("run_once_at", "interval", "interval_type")}),
        ("Результат и статус", {"fields": ("status", "last_error", "last_run")}),
        ("Служебное", {"fields": ("created_at", "updated_at", "meta")}),
    )
    inlines = (TaskFileInline, )

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

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<uuid:task_id>/download_results/",
                self.admin_site.admin_view(self.download_results_view),
                name="task_download_results",
            ),
        ]
        return custom_urls + urls

    def download_results_button(self, obj):
        """Кнопка 'Скачать результаты' в списке задач."""
        if not obj.files.filter(status=TaskFile.Status.DONE).exists():
            return "-"
        url = reverse("admin:task_download_results", args=[obj.id])
        return format_html('<a class="button" href="{}">📥 Скачать результаты</a>', url)

    download_results_button.short_description = "Результаты"
    download_results_button.allow_tags = True

    def download_results_view(self, request, task_id):
        """Формируем zip-архив со всеми результатами файлов задачи."""
        task = self.get_object(request, task_id)
        if not task:
            return HttpResponse("Задача не найдена", status=404)

        task_files = TaskFile.objects.filter(task=task, status=TaskFile.Status.DONE).select_related("filer_file")
        if not task_files.exists():
            return HttpResponse("Нет готовых файлов для выгрузки.", status=400)

        # Формируем общий текст
        result_lines = []
        for tf in task_files:
            header = f"===== {tf.filer_file.original_filename} =====\n"
            text = tf.result_text or "[пусто]"
            result_lines.append(header + text + "\n\n")

        combined_text = "".join(result_lines)

        # Возвращаем txt-файл как attachment
        response = HttpResponse(combined_text, content_type="text/plain; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="task_{task.id}_results.txt"'
        return response

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