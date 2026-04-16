"""
Вспомогательные утилиты жизненного цикла AgentTask.

ensure_task_finalized — страховка против зависания таски в RUNNING.
Вызывается из `finally` блока каждого агента. Если исходный except
упал раньше, чем дошёл до task.save(), или если внутри try бросилось
что-то необычное (OOM, SIGTERM Celery worker, потерян коннект к БД),
таска может застрять в RUNNING и отравить Supervisor/админку.

Мы перечитываем статус из БД и, если всё ещё RUNNING, принудительно
ставим ERROR с дефолтным сообщением. Внутренний try/except защищает
от того, чтобы сама страховка не упала и не перекрыла исходное
исключение.
"""
import logging

from django.utils import timezone

from agents.models import AgentTask

logger = logging.getLogger(__name__)

_DEFAULT_ORPHAN_MESSAGE = "Agent exited без финализации"


def ensure_task_finalized(task: AgentTask, *, fallback_message: str = _DEFAULT_ORPHAN_MESSAGE) -> None:
    """
    Если task всё ещё в RUNNING — принудительно пометить ERROR.

    Безопасен к повторному вызову и к сбоям внутри самого себя.
    """
    try:
        task.refresh_from_db(fields=["status"])
    except Exception:
        logger.exception(
            "ensure_task_finalized: refresh_from_db failed (task_id=%s)", task.pk
        )
        return

    if task.status != AgentTask.RUNNING:
        return

    try:
        task.status = AgentTask.ERROR
        task.error_message = fallback_message
        task.finished_at = timezone.now()
        task.save(update_fields=["status", "error_message", "finished_at"])
        logger.warning(
            "ensure_task_finalized: orphan RUNNING task cleaned up (task_id=%s)",
            task.pk,
        )
        # Telegram-алерт об ошибке
        try:
            from agents.telegram import send_agent_error_alert
            send_agent_error_alert(task)
        except Exception:
            logger.debug("ensure_task_finalized: telegram alert failed (task_id=%s)", task.pk)
    except Exception:
        logger.exception(
            "ensure_task_finalized: save failed (task_id=%s)", task.pk
        )
