import logging
from plyer import notification

logger = logging.getLogger(__name__)


def send_notification(title: str, message: str) -> bool:
    try:
        notification.notify(title=title, message=message, app_name="Daily", timeout=10)
        return True
    except Exception:
        logger.exception("Desktop notification delivery failed")
        return False
