import asyncio
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Добавляем корневую директорию проекта в sys.path
sys.path.append(str(Path(__file__).resolve().parent))

from ai3 import (
    create_test_recommendation,
    find_source_file_for_test,
    get_tested_files,
    monitor_github_actions,
    send_test_recommendation,
)

# Установка таймаута для всех асинхронных тестов
ASYNC_TEST_TIMEOUT = 5  # секунды


@pytest.mark.asyncio
async def test_github_token_present():
    """Проверяет, что токен GitHub присутствует в окружении"""
    # Добавляем явное задание переменной окружения, если она отсутствует (для тестов)
    if "GITHUB_TOKEN" not in os.environ and os.path.exists(".env"):
        # Загружаем переменные из .env файла
        with open(".env", "r") as env_file:
            for line in env_file:
                if line.strip() and not line.startswith("#"):
                    key, value = line.strip().split("=", 1)
                    if key == "GITHUB_TOKEN":
                        os.environ["GITHUB_TOKEN"] = value

    # Устанавливаем таймаут
    try:
        async with asyncio.timeout(ASYNC_TEST_TIMEOUT):
            token = os.environ.get("GITHUB_TOKEN")
            assert token is not None, "GITHUB_TOKEN отсутствует в окружении"
            assert token.startswith(
                "github_pat_"
            ), "GITHUB_TOKEN имеет неправильный формат"
    except asyncio.TimeoutError:
        pytest.fail("Тест превысил таймаут")


@pytest.mark.asyncio
async def test_find_source_file_for_test():
    """Тестирует функцию поиска исходного файла для тестового файла"""
    try:
        async with asyncio.timeout(ASYNC_TEST_TIMEOUT):
            # Мокаем существование файлов
            with patch("os.path.exists", return_value=True):
                source_file = await find_source_file_for_test("test_example.py")
                assert (
                    source_file is not None
                ), "Не удалось найти исходный файл для тестового файла"
    except asyncio.TimeoutError:
        pytest.fail("Тест превысил таймаут")


@pytest.mark.asyncio
async def test_create_test_recommendation():
    """Тестирует функцию создания рекомендаций на основе результатов тестов"""
    try:
        async with asyncio.timeout(ASYNC_TEST_TIMEOUT):
            run_id = "12345"
            conclusion = "success"
            test_files = [{"test_file": "test_example.py", "source_file": "example.py"}]
            html_url = (
                "https://github.com/oleg121203/AI-SYSTEMS-REPO/actions/runs/12345"
            )

            recommendation = await create_test_recommendation(
                run_id, conclusion, test_files, html_url
            )

            assert recommendation is not None, "Рекомендация не была создана"
            assert "run_id" in recommendation, "В рекомендации отсутствует run_id"
            assert "result" in recommendation, "В рекомендации отсутствует результат"
            assert "files" in recommendation, "В рекомендации отсутствуют файлы"
            assert (
                "recommendation" in recommendation
            ), "В рекомендации отсутствует рекомендация"
            assert (
                recommendation["recommendation"] == "accept"
            ), "Должна быть рекомендация accept для успешных тестов"
    except asyncio.TimeoutError:
        pytest.fail("Тест превысил таймаут")


@pytest.mark.asyncio
async def test_get_tested_files():
    """Тестирует функцию получения протестированных файлов"""
    try:
        async with asyncio.timeout(ASYNC_TEST_TIMEOUT):
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = MagicMock(
                return_value={
                    "files": [
                        {"filename": "test_example.py"},
                        {"filename": "example.py"},
                    ]
                }
            )

            # Настраиваем контекстный менеджер для session.get
            mock_session.get.return_value.__aenter__.return_value = mock_response

            # Мокаем find_source_file_for_test для возврата файла-источника
            with patch("ai3.find_source_file_for_test", return_value="example.py"):
                tested_files = await get_tested_files(
                    mock_session,
                    "oleg121203",
                    "AI-SYSTEMS-REPO",
                    "abc123",
                    {"Authorization": "token github_pat_xxx"},
                )

            assert len(tested_files) == 1, "Должен быть найден один тестовый файл"
            assert (
                "test_file" in tested_files[0]
            ), "В результате отсутствует поле test_file"
            assert (
                "source_file" in tested_files[0]
            ), "В результате отсутствует поле source_file"
    except asyncio.TimeoutError:
        pytest.fail("Тест превысил таймаут")


@pytest.mark.asyncio
async def test_send_test_recommendation():
    """Тестирует функцию отправки рекомендаций в API"""
    try:
        async with asyncio.timeout(ASYNC_TEST_TIMEOUT):
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = MagicMock(return_value={"status": "success"})

            # Настраиваем контекстный менеджер для session.post
            mock_session.post.return_value.__aenter__.return_value = mock_response

            recommendation = {
                "run_id": "12345",
                "result": "success",
                "files": [
                    {"test_file": "test_example.py", "source_file": "example.py"}
                ],
                "recommendation": "accept",
            }

            with patch("ai3.get_ai3_api_session", return_value=mock_session):
                result = await send_test_recommendation(recommendation)

            assert (
                result is True
            ), "Функция должна возвращать True при успешной отправке"
    except asyncio.TimeoutError:
        pytest.fail("Тест превысил таймаут")


@pytest.mark.asyncio
async def test_monitor_github_actions_startup():
    """Тестирует запуск функции мониторинга GitHub Actions"""
    try:
        async with asyncio.timeout(ASYNC_TEST_TIMEOUT):
            # Мокаем все зависимости, чтобы избежать реальных запросов
            with patch("ai3.config.get") as mock_config, patch(
                "ai3.get_ai3_api_session"
            ) as mock_session_func, patch(
                "aiohttp.ClientSession.get"
            ) as mock_get, patch(
                "ai3.log_message"
            ) as mock_log:
                # Настраиваем моки
                mock_config.side_effect = lambda key, default=None: {
                    "github_check_interval": 0.1,
                    "github_token": os.environ.get("GITHUB_TOKEN"),
                    "github_repo_owner": "oleg121203",
                    "github_repo_name": "AI-SYSTEMS-REPO",
                }.get(key, default)

                mock_session = MagicMock()
                mock_session_func.return_value = mock_session

                # Настраиваем исключение для остановки бесконечного цикла
                mock_get.side_effect = asyncio.CancelledError()

                # Проверяем, что функция запускается без ошибок до первого CancelledError
                with pytest.raises(asyncio.CancelledError):
                    await monitor_github_actions()

                # Проверяем, что был вызов логирования о запуске мониторинга
                mock_log.assert_called_with(
                    "[AI3-GitHub] Начат мониторинг результатов GitHub Actions"
                )
    except asyncio.TimeoutError:
        pytest.fail("Тест превысил таймаут")


if __name__ == "__main__":
    pytest.main(["-v", "test_github_monitoring.py"])
