# Реактивность в веб-интерфейсах

Учебный статический сайт о производном состоянии в React и Vue. На примере списка задач сайт показывает, как вычислять количество отметок и процент выполнения из исходных данных.

## Запуск

Нужен Python 3.14. Из корня проекта:

```sh
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
lektor --project website server
```

Предпросмотр доступен на `http://127.0.0.1:5000/`. В ходе учебной работы окружение `.venv` было создано с помощью virtualenv. Точные версии этого инструмента и его зависимостей сохранены в `requirements-bootstrap.txt`.

## Сборка и проверка

```sh
lektor --project website build --output-path "$PWD/build" --buildstate-path "$PWD/.cache/reactivity-buildstate"
python scripts/check-site.py --root build
python scripts/check-site.py --root build --base-path /subdir/reactivity/
```

Lektor разрешает относительный путь сборки от каталога проекта `website/`. Абсолютный путь в команде выводит результат в `build/` в корне репозитория. Возврат `1` от генератора или проверки ссылок останавливает сборку в CI. Lektor 3.3.14 выдаёт предупреждение об устаревшем `pkg_resources`, поэтому рабочая версия setuptools закреплена в `requirements.txt`.

В браузере на главной по очереди поставьте три отметки и снимите последнюю. Ожидаемые значения: 0 %, 33 %, 67 %, 100 %, 67 %. В поиске запрос «реактивный массив» ведёт к странице сравнения. Формула отображается нативным MathML даже при выключенном JavaScript.

## Файлы сайта

- `website/content/` — тексты и примеры кода.
- `website/templates/` — HTML-шаблоны Jinja. Шаблон поиска собирает индекс при генерации.
- `website/assets/static/` — CSS, демонстрация и поиск. Для сборки сайта достаточно Python.
- `scripts/check-site.py` — проверка внутренних ссылок, якорей, ресурсов и ссылок из поискового индекса.
- `evidence/02-reactivity/` — результаты локальных проверок и скриншоты для отчёта.

В рабочей копии предыдущие исходники сохранены в `.cache/previous-implementation/lektor-source.tar.gz`.

## Публикация

В репозитории GitHub выберите **Settings → Pages → Source → GitHub Actions**. Workflow `.github/workflows/pages.yml` собирает и проверяет сайт при push в `main`. После публикации он проверяет HTTP-ответ, маркер `reactivity-derived-state` и значение `revision.txt` с SHA коммита.

Для Helios используется отдельный каталог `~/public_html/reactivity/` на `helios.cs.ifmo.ru:2222`. На сервере должны быть доступ к аккаунту и rsync. Добавьте публичный ключ для деплоя в `authorized_keys`. В GitHub Actions задайте секреты `HELIOS_USER` и `HELIOS_SSH_KEY`, переменные `HELIOS_URL` (URL каталога сайта) и `HELIOS_KNOWN_HOSTS` (проверенная запись ключа сервера). Для запуска этапа на Helios установите `HELIOS_ENABLED=true`. При загрузке rsync синхронизирует содержимое выделенного каталога сайта, удаляя из него файлы, отсутствующие в свежей сборке.

Задание `build` собирает сайт один раз. После сборки `deploy-pages` и `deploy-helios` могут выполняться независимо, каждое получает файлы общей сборки в своём артефакте. Настройка `url_style = relative` и фильтр `|url` сохраняют ссылки при переносе в подкаталог.
