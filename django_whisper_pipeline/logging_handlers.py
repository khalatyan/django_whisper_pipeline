import logging
from transcriber.models import TaskLog, Task

class TaskDBHandler(logging.Handler):
    """Логи сохраняются в БД для конкретной задачи (task_id)."""
    def emit(self, record):
        try:
            task_id = getattr(record, "task_id", None)
            if not task_id:
                return
            task = Task.objects.filter(id=task_id).first()
            if not task:
                return
            TaskLog.objects.create(
                task=task,
                level=record.levelname,
                message=self.format(record),
                extra=getattr(record, "extra_data", None)
            )
        except Exception:
            # Не ломаем приложение из-за ошибки логирования
            pass

def get_task_logger(task_id):
    logger = logging.getLogger(f"task_{task_id}")
    if not any(isinstance(h, TaskDBHandler) for h in logger.handlers):
        handler = TaskDBHandler()
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.propagate = False
    # Добавляем task_id в каждый лог
    adapter = logging.LoggerAdapter(logger, extra={"task_id": task_id})
    return adapter
