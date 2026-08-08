"""
Тесты Tor Proxy Manager.

Запуск:  python -m unittest discover -s tests -t .

Сеть не требуется: HTTP-слой подменяется заглушками.
"""
import logging

# Тесты специально проверяют пути отказа — предупреждения в консоли ожидаемы
# и только мешают читать результат.
logging.disable(logging.ERROR)
