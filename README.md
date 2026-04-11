# TorProxy Manager

<p align="center">
  <b>Локальный SOCKS5-прокси через Tor с автоматическим управлением мостами</b><br>
  <sub>obfs4 · webtunnel · vanilla · PyQt5 · Windows</sub>
</p>

---

# 🇷🇺 Русская версия

## Что это

TorProxy Manager - Windows-приложение, которое поднимает локальный **SOCKS5-прокси** (`127.0.0.1:9050`) через сеть Tor с использованием мостов (bridges).

Любая программа - Telegram, браузер, игра - может использовать этот прокси для обхода блокировок. Не нужно ставить Tor Browser, не нужно вручную искать мосты, не нужно править конфиги.

### Чем отличается от Tor Browser

| | Tor Browser | TorProxy Manager |
|---|---|---|
| Что проксирует | Только встроенный Firefox | Любое приложение через SOCKS5 |
| Мосты | Ручной ввод или запрос через BridgeDB | Автоматический сбор, тестирование и ротация |
| Восстановление при обрыве | Ручное переподключение | Автоматическое (watchdog + NEWNYM + ротация мостов) |
| Интерфейс | Браузер | Компактная панель в системном трее |

## Как это работает

### Компоненты системы

| Компонент | Роль |
|-----------|------|
| **Tor** (`tor.exe`) | Ядро - строит зашифрованные цепочки через 3 узла сети Tor |
| **lyrebird** (`lyrebird.exe`) | Pluggable Transport - маскирует трафик Tor под обычный HTTPS/WebSocket, чтобы DPI не мог его отличить |
| **Мосты (bridges)** | Незафиксированные в публичных каталогах входные узлы Tor. Провайдер не знает их IP - не может заблокировать |
| **SOCKS5-прокси** | Локальный порт `127.0.0.1:9050`, через который приложения отправляют трафик в Tor |

### Схема работы

```
Приложение (Telegram, браузер, ...)
    │
    ▼
SOCKS5 прокси (127.0.0.1:9050)
    │
    ▼
Tor core ── шифрует и строит цепочку из 3 узлов
    │
    ▼
lyrebird (Pluggable Transport) ── маскирует трафик под HTTPS
    │
    ▼
Bridge (мост) ── входной узел, невидимый для провайдера
    │
    ▼
Relay → Relay → Exit Node → Интернет
```

### Типы мостов

| Тип | Маскировка | Рекомендация |
|-----|-----------|--------------|
| **obfs4** | Трафик выглядит как случайный шум - не опознаётся DPI | Рекомендуется для большинства сетей |
| **webtunnel** | Трафик маскируется под обычный HTTPS к CDN | Для сетей, где obfs4 заблокирован |
| **vanilla** | Без маскировки - прямое подключение к мосту | Только для сетей без DPI |

## Возможности

- **Автоматический сбор мостов** - параллельная загрузка из 8+ открытых источников с дедупликацией по fingerprint и IP
- **Тестирование мостов** - TCP-проба для obfs4/vanilla, TLS handshake с проверкой сертификата для webtunnel
- **Валидация формата** - отсев мостов без обязательных полей, с приватными IP, из чёрного списка
- **SOCKS5-прокси** на `127.0.0.1:9050` (порт настраивается)
- **Adaptive watchdog** - автоматическое восстановление соединения:
  - Трёхфазная диагностика: нет интернета → Tor ещё грузится → Tor завис
  - NEWNYM (пересоздание circuits) через ControlPort без перезапуска
  - Ротация мостов после 3 неудач подряд
  - Автоматический перезапуск как крайняя мера
- **Bootstrap watchdog** - если мосты не дали прогресс ≥10% за 90 секунд → авто-обновление мостов
- **Проксирование приложений** - запуск любого `.exe` через Tor:
  - Chromium-браузеры → `--proxy-server` (нативно)
  - Firefox → отдельный профиль с SOCKS5
  - Остальные → proxychains-windows
- **Авто-обновление мостов** - настраиваемый интервал (по умолчанию 24 часа), фоновое обновление без разрыва соединения
- **Генерация torrc** - оптимизирован для обхода DPI: KeepalivePeriod 60, адаптивные таймауты, Microdescriptors
- **Системный трей** - сворачивание в трей, управление из контекстного меню
- **Два языка** - русский и английский интерфейс
- **Логирование** - отдельные лог-файлы: `tor.log`, `watchdog.log`, `errors.log`

## Установка

### Для пользователей (готовый .exe)

1. Скачайте `TorProxyManager_v1.0.zip` со страницы [Releases](../../releases)
2. Распакуйте архив
3. Запустите `TorProxyManager.exe`

### Внешние зависимости (не входят в репозиторий)

TorProxy Manager - это **управляющая оболочка**. Сам Tor и транспорты - это отдельные бинарники, которые нужно получить самостоятельно.

#### Tor (обязательно)

Для работы программы нужны 4 файла:

| Файл | Назначение |
|------|-----------|
| `tor.exe` | Ядро Tor - строит зашифрованные цепочки |
| `lyrebird.exe` | Pluggable Transport - маскирует трафик (obfs4, webtunnel) |
| `geoip` | База геолокации IPv4 (нужна Tor для выбора узлов) |
| `geoip6` | База геолокации IPv6 |

**Где взять:**
- [Tor Expert Bundle](https://www.torproject.org/download/tor/) - скачайте архив, внутри найдёте все 4 файла
- Или из установленного **Tor Browser**: папка `Browser/TorBrowser/Tor/`

**Куда положить:**

**Вариант A (рекомендуется):** создайте папку `tor/` рядом с `TorProxyManager.exe` и положите файлы туда - приложение найдёт их автоматически:
```
TorProxyManager/
├── TorProxyManager.exe
└── tor/
    ├── tor.exe
    ├── lyrebird.exe
    ├── geoip
    └── geoip6
```

**Вариант B:** положите файлы куда угодно и укажите пути вручную в **Настройках** → «Путь к tor.exe» / «Путь к lyrebird.exe». Приложение также умеет находить Tor Browser в стандартных папках (`Program Files`, `Desktop`, `AppData`).

#### proxychains-windows (опционально)

Нужен только если вы хотите проксировать через Tor **произвольные .exe-приложения** (не браузеры - для браузеров proxychains не нужен).

1. Скачайте последний релиз с [shunf4/proxychains-windows](https://github.com/shunf4/proxychains-windows/releases)
2. Из архива вам нужны 3 файла:
   - `proxychains_win32_x64.exe` - основной исполняемый файл
   - `proxychains_hook_x64.dll` - DLL-хук для перехвата Winsock
   - `proxychains_helper_win32_x64.exe` - вспомогательный процесс
3. Создайте папку `tools/` рядом с `TorProxyManager.exe` и положите файлы туда:
```
TorProxyManager/
├── TorProxyManager.exe
├── tor/
│   └── ...
└── tools/
    ├── proxychains_win32_x64.exe
    ├── proxychains_hook_x64.dll
    └── proxychains_helper_win32_x64.exe
```

> Без proxychains браузеры всё равно будут работать - Chrome/Edge/Brave используют нативный `--proxy-server`, Firefox - отдельный профиль. Proxychains нужен только для программ, которые не поддерживают прокси сами.

### Для разработчиков

**Требования:** Python 3.10+, Windows 10/11

```bash
git clone https://github.com/your-username/tor-proxy-manager
cd tor-proxy-manager

pip install -r requirements.txt

# Запуск из исходников:
python main.py
```

`requirements.txt` содержит единственную зависимость:
```
PyQt5>=5.15.0
```

## Сборка EXE

```bash
# Установить PyInstaller (если не установлен):
pip install pyinstaller

# Собрать:
python -m PyInstaller build.spec --noconfirm
```

Результат: `dist/TorProxyManager.exe` (onefile, ~50 МБ)

### Структура проекта

```
tor_proxy_manager/
├── main.py                  # Точка входа, single-instance mutex
├── build.spec               # PyInstaller spec (onefile)
├── requirements.txt
├── translations/
│   ├── ru.json              # Русский интерфейс
│   └── en.json              # English interface
├── core/
│   ├── config.py            # Конфигурация, пути, автозапуск
│   ├── tor_manager.py       # Управление tor.exe, watchdog'и
│   ├── torrc_builder.py     # Генерация torrc
│   ├── bridge_fetcher.py    # Параллельный сбор мостов
│   ├── bridge_tester.py     # TCP/TLS тестирование мостов
│   ├── bridge_validator.py  # Валидация формата и IP
│   ├── app_proxy.py         # Запуск приложений через прокси
│   └── i18n.py              # Система переводов
├── gui/
│   ├── main_window.py       # Главное окно
│   ├── settings_dialog.py   # Настройки
│   ├── tray_icon.py         # Системный трей
│   ├── app_proxy_widget.py  # UI управления приложениями
│   └── styles.py            # Тёмная тема
└── dist/
    └── TorProxyManager.exe  # Собранный EXE
```

## Использование

### Быстрый старт

1. Запустите `TorProxyManager.exe`
2. Выберите тип мостов (по умолчанию **obfs4**)
3. Нажмите **Обновить** - приложение загрузит и протестирует мосты
4. Нажмите **Подключить** - дождитесь bootstrap 100%
5. Статус **Подключено** → прокси активен на `127.0.0.1:9050`

### Настройка приложений

| Приложение | Как подключить |
|-----------|---------------|
| **Telegram** | Настройки → Продвинутые → Тип подключения → SOCKS5 → хост `127.0.0.1`, порт `9050` |
| **Firefox** | Настройки → Сеть → Настройки соединения → Ручная → SOCKS-хост `127.0.0.1`, порт `9050`, SOCKS v5, ✓ Proxy DNS |
| **Chrome / Edge / Brave** | Расширение [Proxy SwitchyOmega](https://chromewebstore.google.com/detail/proxy-switchyomega/) → SOCKS5 → `127.0.0.1:9050` |
| **Любой .exe** | Раздел «Приложения через прокси» в главном окне → кнопка «+ Добавить» |

### Из панели приложения

Встроенный лаунчер автоматически выбирает лучший метод:
- **Chrome/Edge/Brave/Yandex** → нативный `--proxy-server` с отдельным профилем
- **Firefox** → отдельный профиль с SOCKS5 в `user.js`
- **Другие .exe** → proxychains-windows (перехват Winsock)
- **Fallback** → переменные окружения `HTTP_PROXY` / `ALL_PROXY`

## Конфигурация

Конфиг хранится в `%USERPROFILE%\.tor_proxy_manager\config.json`.

### Настраиваемые параметры

| Параметр | По умолчанию | Описание |
|----------|-------------|----------|
| `socks_port` | `9050` | Порт SOCKS5-прокси |
| `bridge_type` | `obfs4` | Тип мостов: `obfs4`, `webtunnel`, `vanilla` |
| `max_bridges` | `5` | Количество лучших мостов для использования |
| `test_timeout` | `5` | Таймаут тестирования моста (секунды) |
| `auto_update_hours` | `24` | Интервал автообновления мостов (часы) |
| `language` | `ru` | Язык интерфейса: `ru`, `en` |

### torrc

Файл `torrc` генерируется автоматически при каждом подключении. Вручную его редактировать не нужно.

Ключевые параметры, которые выставляет приложение:
- `SocksPort 127.0.0.1:9050` - SOCKS5 только на localhost
- `ControlPort 127.0.0.1:9051` - для watchdog (NEWNYM, bootstrap status)
- `UseBridges 1` + `ClientTransportPlugin` - активация мостов
- `KeepalivePeriod 60` - быстрое обнаружение мёртвых соединений
- `CircuitBuildTimeout 30` - адаптивный таймаут для мостов

### Чего НЕЛЬЗЯ делать

- **Не ставить `Socks5Proxy 127.0.0.1:9050`** в torrc - Tor зациклит трафик на самого себя
- **Не менять `DataDirectory`** вручную - приложение управляет этим путём
- **Не запускать несколько экземпляров** - порт будет занят, Tor не стартует
- **Не блокировать `lyrebird.exe`** в файрволе - без него obfs4/webtunnel не работают

## Устранение проблем

### Зависание на 95% bootstrap

**Причина:** Tor скачивает consensus (~2-3 МБ) через мост. Если circuit обрывается во время скачивания - процесс начинается заново.

**Решение:**
- Подождите 2-3 минуты - это нормально для мостов
- Если не помогает - смените тип мостов (obfs4 → webtunnel или наоборот)
- Нажмите **Обновить** для получения свежих мостов

### SOCKS5 работает, но интернет не открывается

**Причина:** Tor подключен, но выходной узел (exit node) может быть перегружен или заблокирован целевым сайтом.

**Решение:**
- Подождите 30 секунд - watchdog автоматически выполнит NEWNYM (смена цепочки)
- Если не помогает - переподключитесь (Отключить → Подключить)

### Мосты не подключаются (0% bootstrap)

**Причина:** Все мосты заблокированы в вашей сети, или `lyrebird.exe` не найден.

**Решение:**
- Проверьте путь к `lyrebird.exe` в Настройках
- Попробуйте другой тип мостов
- Нажмите **Обновить** - приложение загрузит свежие мосты
- Watchdog автоматически обновит мосты через 90 секунд

### Отключение после обрыва сети (Wi-Fi/VPN)

**Причина:** OR-соединения Tor разорваны при смене сети.

**Решение:** Watchdog обнаружит проблему через 15-20 секунд и:
1. Попробует NEWNYM (пересоздать circuits)
2. Если не помогло - перезапустит Tor автоматически
3. После 3 неудач подряд - выполнит ротацию моста

Ручного вмешательства обычно не требуется.

### Порт уже занят

**Причина:** Предыдущий экземпляр Tor не завершился корректно.

**Решение:** Приложение автоматически находит и убивает осиротевшие процессы. Если проблема сохраняется - смените порт в Настройках или перезагрузите компьютер.

## Может ли РКН заблокировать этот способ?

Краткий ответ: **крайне маловероятно в ближайшей перспективе**.

Tor через мосты с Pluggable Transports (obfs4, webtunnel) - один из самых устойчивых методов обхода блокировок. Вот почему:

- **obfs4** делает трафик неотличимым от случайного шума - DPI не может его классифицировать как «Tor» и вынужден либо пропустить, либо заблокировать **весь** нераспознанный трафик (что сломает легитимные сервисы)
- **webtunnel** маскирует трафик под обычный HTTPS к CDN-серверам (Cloudflare, Amazon и т.д.). Блокировка этих CDN означает недоступность огромной части интернета
- **IP-адреса мостов не публикуются** - в отличие от обычных relay-нод, мосты не перечислены в публичных каталогах Tor. РКН не может получить полный список для блокировки
- **Мосты постоянно обновляются** - даже если конкретный мост заблокирован, приложение автоматически загружает свежие из нескольких источников

Даже Китай (Great Firewall) и Иран, которые вкладывают значительно больше ресурсов в DPI, не смогли полностью заблокировать Tor через мосты - они периодически блокируют часть мостов, но сеть адаптируется.

> **Тем не менее**, гарантий нет. Теоретически РКН может внедрить анализ паттернов трафика или активное зондирование (active probing) для обнаружения obfs4. Если obfs4 перестанет работать - переключитесь на webtunnel, и наоборот.

## Планы на другие платформы

| Платформа | Статус |
|-----------|--------|
| **Windows** | Готово (текущая версия) |
| **Android** | В планах - APK-приложение |
| **iOS** | Маловероятно - Apple не допускает приложения для обхода цензуры в App Store, а sideloading на iOS сильно ограничен |

## Безопасность

> **TorProxy Manager - инструмент обхода цензуры, а не гарантия полной анонимности.**

- Приложения, не настроенные на работу через SOCKS5, отправляют трафик напрямую и раскрывают ваш IP
- DNS-запросы проксируются только если приложение отправляет их через SOCKS5 (Proxy DNS)
- Операторы мостов видят факт подключения к Tor, но не содержимое трафика
- Для максимальной анонимности используйте [Tor Browser](https://www.torproject.org/download/)
- Автор не несёт ответственности за использование данного ПО

## Лицензия

MIT License - см. [LICENSE](LICENSE)

---

# 🇬🇧 English version

## What is this

TorProxy Manager is a Windows application that runs a local **SOCKS5 proxy** (`127.0.0.1:9050`) through the Tor network using bridges.

Any application — Telegram, a browser, a game — can use this proxy to bypass censorship. No need to install Tor Browser, manually find bridges, or edit config files.

### How is this different from Tor Browser

| | Tor Browser | TorProxy Manager |
|---|---|---|
| What gets proxied | Built-in Firefox only | Any application via SOCKS5 |
| Bridges | Manual entry or BridgeDB request | Automatic collection, testing and rotation |
| Recovery on disconnect | Manual reconnect | Automatic (watchdog + NEWNYM + bridge rotation) |
| Interface | Full browser | Compact tray panel |

## How it works

### Components

| Component | Role |
|-----------|------|
| **Tor** (`tor.exe`) | Core — builds encrypted circuits through 3 Tor relay nodes |
| **lyrebird** (`lyrebird.exe`) | Pluggable Transport — disguises Tor traffic as regular HTTPS/WebSocket so DPI cannot detect it |
| **Bridges** | Unlisted Tor entry nodes. Your ISP doesn't know their IPs — can't block them |
| **SOCKS5 proxy** | Local port `127.0.0.1:9050` where applications send traffic into Tor |

### Traffic flow

```
Application (Telegram, browser, ...)
    │
    ▼
SOCKS5 proxy (127.0.0.1:9050)
    │
    ▼
Tor core ── encrypts and builds a 3-node circuit
    │
    ▼
lyrebird (Pluggable Transport) ── disguises traffic as HTTPS
    │
    ▼
Bridge ── entry node invisible to ISP
    │
    ▼
Relay → Relay → Exit Node → Internet
```

### Bridge types

| Type | Disguise | Recommendation |
|------|----------|----------------|
| **obfs4** | Traffic looks like random noise — unrecognizable by DPI | Recommended for most networks |
| **webtunnel** | Traffic disguised as regular HTTPS to a CDN | For networks where obfs4 is blocked |
| **vanilla** | No disguise — direct connection to bridge | Only for networks without DPI |

## Features

- **Automatic bridge collection** — parallel fetch from 8+ open sources with fingerprint and IP deduplication
- **Bridge testing** — TCP probe for obfs4/vanilla, TLS handshake with certificate validation for webtunnel
- **Format validation** — rejects bridges with missing fields, private IPs, blacklisted addresses
- **SOCKS5 proxy** at `127.0.0.1:9050` (port configurable)
- **Adaptive watchdog** — automatic connection recovery:
  - Three-phase diagnosis: no internet → Tor still bootstrapping → Tor stale
  - NEWNYM (circuit recreation) via ControlPort without restart
  - Bridge rotation after 3 consecutive failures
  - Automatic restart as last resort
- **Bootstrap watchdog** — if bridges don't reach ≥10% progress in 90 seconds → auto-update bridges
- **Per-app proxying** — launch any `.exe` through Tor:
  - Chromium browsers → native `--proxy-server` with separate profile
  - Firefox → separate profile with SOCKS5 in `user.js`
  - Others → proxychains-windows
- **Auto-update bridges** — configurable interval (default 24 hours), background update without disconnecting
- **torrc generation** — optimized for DPI bypass: KeepalivePeriod 60, adaptive timeouts, Microdescriptors
- **System tray** — minimize to tray, context menu control
- **Two languages** — Russian and English interface
- **Logging** — separate log files: `tor.log`, `watchdog.log`, `errors.log`

## Installation

### For users (pre-built .exe)

1. Download `TorProxyManager_v1.0.zip` from the [Releases](../../releases) page
2. Extract the archive
3. Run `TorProxyManager.exe`

### External dependencies (not included in the repository)

TorProxy Manager is a **management shell**. Tor itself and transports are separate binaries that you need to obtain separately.

#### Tor (required)

4 files are needed:

| File | Purpose |
|------|---------|
| `tor.exe` | Tor core — builds encrypted circuits |
| `lyrebird.exe` | Pluggable Transport — disguises traffic (obfs4, webtunnel) |
| `geoip` | IPv4 geolocation database (needed by Tor for node selection) |
| `geoip6` | IPv6 geolocation database |

**Where to get them:**
- [Tor Expert Bundle](https://www.torproject.org/download/tor/) — download the archive, all 4 files are inside
- Or from an installed **Tor Browser**: folder `Browser/TorBrowser/Tor/`

**Where to put them:**

**Option A (recommended):** create a `tor/` folder next to `TorProxyManager.exe` and put the files there — the app will find them automatically:
```
TorProxyManager/
├── TorProxyManager.exe
└── tor/
    ├── tor.exe
    ├── lyrebird.exe
    ├── geoip
    └── geoip6
```

**Option B:** place the files anywhere and set the paths manually in **Settings** → "Path to tor.exe" / "Path to lyrebird.exe". The app also searches for Tor Browser in standard locations (`Program Files`, `Desktop`, `AppData`).

#### proxychains-windows (optional)

Only needed if you want to proxy **arbitrary .exe applications** through Tor (not needed for browsers — they have native proxy support).

1. Download the latest release from [shunf4/proxychains-windows](https://github.com/shunf4/proxychains-windows/releases)
2. From the archive you need 3 files:
   - `proxychains_win32_x64.exe` — main executable
   - `proxychains_hook_x64.dll` — Winsock interception DLL
   - `proxychains_helper_win32_x64.exe` — helper process
3. Create a `tools/` folder next to `TorProxyManager.exe` and place the files there:
```
TorProxyManager/
├── TorProxyManager.exe
├── tor/
│   └── ...
└── tools/
    ├── proxychains_win32_x64.exe
    ├── proxychains_hook_x64.dll
    └── proxychains_helper_win32_x64.exe
```

> Without proxychains, browsers still work — Chrome/Edge/Brave use native `--proxy-server`, Firefox uses a separate profile. Proxychains is only needed for apps that don't support proxies natively.

### For developers

**Requirements:** Python 3.10+, Windows 10/11

```bash
git clone https://github.com/your-username/tor-proxy-manager
cd tor-proxy-manager

pip install -r requirements.txt

# Run from source:
python main.py
```

`requirements.txt` contains a single dependency:
```
PyQt5>=5.15.0
```

## Building the EXE

```bash
# Install PyInstaller (if not installed):
pip install pyinstaller

# Build:
python -m PyInstaller build.spec --noconfirm
```

Output: `dist/TorProxyManager.exe` (onefile, ~50 MB)

### Project structure

```
tor_proxy_manager/
├── main.py                  # Entry point, single-instance mutex
├── build.spec               # PyInstaller spec (onefile)
├── requirements.txt
├── translations/
│   ├── ru.json              # Russian interface
│   └── en.json              # English interface
├── core/
│   ├── config.py            # Configuration, paths, autostart
│   ├── tor_manager.py       # Tor process management, watchdogs
│   ├── torrc_builder.py     # torrc generation
│   ├── bridge_fetcher.py    # Parallel bridge fetching
│   ├── bridge_tester.py     # TCP/TLS bridge testing
│   ├── bridge_validator.py  # Format and IP validation
│   ├── app_proxy.py         # Per-app proxy launcher
│   └── i18n.py              # Translation system
├── gui/
│   ├── main_window.py       # Main window
│   ├── settings_dialog.py   # Settings dialog
│   ├── tray_icon.py         # System tray
│   ├── app_proxy_widget.py  # App proxy management UI
│   └── styles.py            # Dark theme
└── dist/
    └── TorProxyManager.exe  # Built executable
```

## Usage

### Quick start

1. Launch `TorProxyManager.exe`
2. Select bridge type (default: **obfs4**)
3. Click **Update** — the app will fetch and test bridges
4. Click **Connect** — wait for bootstrap to reach 100%
5. Status **Connected** → proxy is live at `127.0.0.1:9050`

### Configuring applications

| Application | How to connect |
|------------|---------------|
| **Telegram** | Settings → Advanced → Connection Type → SOCKS5 → host `127.0.0.1`, port `9050` |
| **Firefox** | Settings → Network → Connection Settings → Manual → SOCKS Host `127.0.0.1`, Port `9050`, SOCKS v5, ✓ Proxy DNS |
| **Chrome / Edge / Brave** | Extension [Proxy SwitchyOmega](https://chromewebstore.google.com/detail/proxy-switchyomega/) → SOCKS5 → `127.0.0.1:9050` |
| **Any .exe** | "Applications via proxy" section in the main window → "+ Add" button |

### Built-in app launcher

The launcher automatically selects the best method:
- **Chrome/Edge/Brave/Yandex** → native `--proxy-server` with separate profile
- **Firefox** → separate profile with SOCKS5 in `user.js`
- **Other .exe** → proxychains-windows (Winsock interception)
- **Fallback** → environment variables `HTTP_PROXY` / `ALL_PROXY`

## Configuration

Config is stored in `%USERPROFILE%\.tor_proxy_manager\config.json`.

### Configurable parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `socks_port` | `9050` | SOCKS5 proxy port |
| `bridge_type` | `obfs4` | Bridge type: `obfs4`, `webtunnel`, `vanilla` |
| `max_bridges` | `5` | Number of top bridges to use |
| `test_timeout` | `5` | Bridge test timeout (seconds) |
| `auto_update_hours` | `24` | Bridge auto-update interval (hours) |
| `language` | `ru` | Interface language: `ru`, `en` |

### torrc

The `torrc` file is generated automatically on every connect. Manual editing is not needed.

Key parameters set by the app:
- `SocksPort 127.0.0.1:9050` — SOCKS5 on localhost only
- `ControlPort 127.0.0.1:9051` — for watchdog (NEWNYM, bootstrap status)
- `UseBridges 1` + `ClientTransportPlugin` — bridge activation
- `KeepalivePeriod 60` — fast detection of dead connections
- `CircuitBuildTimeout 30` — adaptive timeout for bridges

### What NOT to do

- **Do not set `Socks5Proxy 127.0.0.1:9050`** in torrc — Tor will loop traffic into itself
- **Do not change `DataDirectory`** manually — the app manages this path
- **Do not run multiple instances** — the port will be busy, Tor won't start
- **Do not block `lyrebird.exe`** in your firewall — obfs4/webtunnel won't work without it

## Troubleshooting

### Stuck at 95% bootstrap

**Cause:** Tor is downloading the consensus (~2-3 MB) through a bridge. If the circuit drops during download — the process restarts.

**Solution:**
- Wait 2-3 minutes — this is normal for bridges
- If it persists — switch bridge type (obfs4 → webtunnel or vice versa)
- Click **Update** to fetch fresh bridges

### SOCKS5 works but no internet

**Cause:** Tor is connected, but the exit node may be overloaded or blocked by the target site.

**Solution:**
- Wait 30 seconds — watchdog will automatically send NEWNYM (circuit change)
- If it persists — reconnect (Disconnect → Connect)

### Bridges won't connect (0% bootstrap)

**Cause:** All bridges are blocked in your network, or `lyrebird.exe` is missing.

**Solution:**
- Check the `lyrebird.exe` path in Settings
- Try a different bridge type
- Click **Update** — the app will fetch fresh bridges
- Watchdog will automatically update bridges after 90 seconds

### Disconnection after network change (Wi-Fi/VPN)

**Cause:** Tor OR-connections drop when the network changes.

**Solution:** Watchdog detects the issue within 15-20 seconds and:
1. Tries NEWNYM (recreate circuits)
2. If that fails — automatically restarts Tor
3. After 3 consecutive failures — rotates the bridge

No manual intervention is usually needed.

### Port already in use

**Cause:** A previous Tor instance didn't shut down cleanly.

**Solution:** The app automatically finds and kills orphaned processes. If the problem persists — change the port in Settings or restart your computer.

## Can RKN (Russian censor) block this method?

Short answer: **highly unlikely in the near future**.

Tor with bridges and Pluggable Transports (obfs4, webtunnel) is one of the most resilient censorship circumvention methods. Here's why:

- **obfs4** makes traffic indistinguishable from random noise — DPI cannot classify it as "Tor" and would have to either pass it or block **all** unrecognized traffic (which would break legitimate services)
- **webtunnel** disguises traffic as regular HTTPS to CDN servers (Cloudflare, Amazon, etc.). Blocking these CDNs would make a huge portion of the internet inaccessible
- **Bridge IPs are not published** — unlike regular Tor relay nodes, bridges are not listed in public Tor catalogs. The censor cannot obtain a full list for blocking
- **Bridges are constantly updated** — even if a specific bridge is blocked, the app automatically fetches fresh ones from multiple sources

Even China (Great Firewall) and Iran, which invest significantly more resources in DPI, have been unable to fully block Tor via bridges — they periodically block some bridges, but the network adapts.

> **However**, there are no guarantees. Theoretically, censors could deploy traffic pattern analysis or active probing to detect obfs4. If obfs4 stops working — switch to webtunnel, and vice versa.

## Platform plans

| Platform | Status |
|----------|--------|
| **Windows** | Ready (current version) |
| **Android** | Planned — APK app |
| **iOS** | Unlikely — Apple does not allow censorship circumvention apps in the App Store, and sideloading on iOS is heavily restricted |

## Security

> **TorProxy Manager is a censorship circumvention tool — not a guarantee of full anonymity.**

- Applications not configured to use SOCKS5 send traffic directly and expose your IP
- DNS queries are only proxied if the application sends them through SOCKS5 (Proxy DNS)
- Bridge operators can see that you're connecting to Tor, but not your traffic content
- For maximum anonymity, use [Tor Browser](https://www.torproject.org/download/)
- The author is not responsible for any misuse of this software

## License

MIT License — see [LICENSE](LICENSE)

---

## Acknowledgements / Благодарности

- [The Tor Project](https://www.torproject.org/) — Tor core and pluggable transports
- [Delta-Kronecker/Tor-Bridges-Collector](https://github.com/Delta-Kronecker/Tor-Bridges-Collector) — priority bridge source
- [scriptzteam/Tor-Bridges-Collector](https://github.com/scriptzteam/Tor-Bridges-Collector) — standard bridge source
- [proxychains-windows](https://github.com/shunf4/proxychains-windows) — Winsock proxy interception
