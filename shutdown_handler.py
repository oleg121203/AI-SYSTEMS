import asyncio
import logging
import signal
from typing import Optional

from providers import ProviderFactory

logger = logging.getLogger(__name__)


async def shutdown(signal: signal.Signals, loop: asyncio.AbstractEventLoop):
    """Корректное завершение при получении сигнала."""
    logger.info(f"Получен сигнал {signal.name}, завершение...")

    # Закрываем сессии всех провайдеров
    await ProviderFactory.close_all_providers()

    # Отменяем оставшиеся задачи
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()

    logger.info(f"Отменено {len(tasks)} задач")
    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()


def register_shutdown_handlers():
    """Регистрация обработчиков сигналов для корректного завершения."""
    loop = asyncio.get_event_loop()
    for s in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(s, lambda s=s: asyncio.create_task(shutdown(s, loop)))
    logger.info("Зарегистрированы обработчики сигналов для корректного завершения")
