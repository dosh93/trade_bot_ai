**Bybit GPT Bot**

Торговый бот для Bybit USDT perpetual (через ccxt), принимающий решения от ChatGPT (OpenAI API). Работает по закрытым свечам выбранного таймфрейма, ставит только лимитные ордера, умеет TP/SL, отмену ордеров, закрытие позиции и запрос дополнительных данных (в пределах лимита). На последней попытке запроса данных модель обязана вернуть терминальное действие.

ВНИМАНИЕ: при `exchange.testnet=false` — реальная торговля. Убедитесь в рисках и правах API-ключей.

**Быстрый старт (локально)**
- Требуется Python 3.11+
- Установите зависимости: `pip install -e .[dev]` из корня проекта `bybit-gpt-bot`
- Создайте `.env` на основе `.env.sample` и укажите ключи:
  - `OPENAI_API_KEY`
  - `BYBIT_API_KEY`
  - `BYBIT_API_SECRET`
- Скопируйте `config.example.yaml` в `config.yaml` и при необходимости измените параметры.
- Проверка подключения и настроек:
  - `python -m bot check --config config.yaml`
- Запуск одного цикла на последней закрытой свече:
  - `python -m bot once --config config.yaml`
- Запуск бесконечного цикла:
  - `python -m bot run --config config.yaml`

Параметры CLI перекрывают конфиг. Часть настроек также может быть перекрыта переменными окружения с префиксом `BGB__`, например: `BGB__EXCHANGE__SYMBOL=BTC/USDT:USDT`.

**Запуск в Docker**
- Собрать: `docker build -t bybit-gpt-bot .`
- Подготовить файлы: `.env`, `config.yaml`
- Запуск:
  - `docker run --rm -it --env-file .env -v $(pwd)/config.yaml:/app/config.yaml:ro bybit-gpt-bot`

**Пример ответа модели (JSON)**
```
{
  "action": "place_order",
  "idempotency_key": "entry-eth-20240901-1200",
  "params": {
    "side": "buy",
    "price": 2800.5,
    "qty": 0.2,
    "take_profit": 2840.0,
    "stop_loss": 2785.0,
    "post_only": null,
    "time_in_force": "GTC"
  }
}
```

**Пример лога цикла place_order (фрагмент)**
```
[INFO] Snapshot built for ETH/USDT:USDT@5m, candles=200
[INFO] Decision: place_order key=entry-eth-20240901-1200
[INFO] Risk checks passed: orders/hour=2/10, open_orders=1/5, max_position_usdt=400/1000
[INFO] Normalized price=2800.5 qty=0.2
[INFO] Placing LIMIT buy 0.2 @ 2800.5 clientOrderId=gptbot-1693567200-x7asf
[INFO] Order placed id=1234567890; attaching TP/SL if supported
```

**Конфигурация**
- Загружается в порядке приоритета:
  1) `.env` (если есть)
  2) YAML-конфиг (`--config`)
  3) Переменные окружения `BGB__...` перекрывают YAML
  4) Флаги CLI перекрывают всё выше

Смотрите `config.example.yaml` для значений по умолчанию.

**Тесты**
- Запуск: `pytest`
- Покрывают:
  - нормализацию цены/количества к шагам рынка
  - валидацию схемы ответов и запрет `request_data` на последней попытке
  - идемпотентность действий по `idempotency_key`

**Предупреждение**
- При `exchange.testnet=false` — операции реальными средствами. Используйте на свой риск.

