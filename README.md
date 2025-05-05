# Давай с нами бот

![Test & deploy](https://github.com/magusch/ChannelBot/workflows/Basic%20CI/badge.svg)
[![CodeFactor](https://www.codefactor.io/repository/github/magusch/channelbot/badge?s=2dddd084faca7dfc56c595e695a9ecf05d98207c)](https://www.codefactor.io/repository/github/magusch/channelbot)

- [Update tables](#update-tables)
- [Database module](#database)
- [Contributing to `channelbot`](#contributing-to-channelbot)

## Требования к окружению
Константы:
 - `TIMEPAD_TOKEN` - токен от сайта timepad.ru
 - `BOT_TOKEN` - токен для телеграм бота
 - `DATABASE_URL` - URI от базы данных на heroku
 - `CHANNEL_ID` - ID основного телеграм канала
 - `DEV_CHANNEL_ID` - ID телеграм канала (_для разработки_)
 - `VK_TOKEN` - токен от ВКонтакте
 - `VK_USER_ID` - ID пользователя в ВКонтакте
 - `VK_GROUP_ID` - ID группы для постинга
 - `VK_DEV_GROUP_ID` - ID группы для постинга (_для разработки_)
 - `DSN_USERNAME` - имя пользователя с полным доступом от сайта dsn.4geek.ru
 - `DSN_PASSWORD` - пароль для пользователя с полным доступом на сайте dsn.4geek.ru


## Update tables
Для обновления таблиц с мероприятиями, можно запустить скрипт
```bash
python update_tables.py
```

## Database

```python
>>> from davai_s_nami_bot import database
```

Доступные функции для работы с базой данных мероприятий.

Просмотр всех мероприятий в удобном формате:
```python
>>> events = database.get_all()
>>> type(events)
pandas.core.frame.DataFrame
>>> events.columns
Index(['id', 'title', 'post_id', 'date_from', 'date_to', 'price'], dtype='object')
```

Удаление мероприятий из базы данных возможно по `event_id`  или по `title`:
```python
>>> database.remove_by_event_id(event_id)
>>> database.remove_by_title(title)
```

## Contributing to `channelbot`
Для добавления нового функционала в текущую версию `channelbot` необходимо придерживаться простых правил:

**1. Не пушить напрямую в `master` ветку**  
Избегать выполнения подобной команды
```
$ git push origin master
```
или тем более force-push
```
$ git push -f origin master
```

**2. Работать в отдельных ветках**  
Для работы над новым функционалом или исправлением текущего функционала (_для сколь угодно мелких изменений_) использовать новые ветки (созданные от актуальной ветки `master`).  
В случае, когда во время работы в другой ветке, ветка `master` обновилась, необходимо обновить свою ветку путём слияния ветки `master` в свою (создание `pull request` не обязательно).

**3. Обязательное выполнение ВСЕХ тестов перед сливанием `pull request`**  
После окончания работы над новым функционал (или исправлением текущего функционала), необходимо создать `pull request` и дождаться, пока пройдут все тесты.  
В случае, когда тесты не прошли, необходимо ознакомиться с логом выполнения всех тестов (там указано какой тест и с какой ошибкой сломался) и исправить проблему, путем коммита в текущую ветку (`pull request` обновится в соответствии с новым коммитом).

**4. Code style**  
В тестах предусмотрена проверка стиля кода автоматическими утилитами. Перед созданием `pull request` необходимо у себя (локально) запустить эти утилиты и исправить все проблемы. Для запуска использовать следующие команды:
```bash
$ isort --recursive --check --project davai_s_nami_bot --diff .
$ black --check --line-length=89 .
$ autoflake --check --recursive --remove-all-unused-imports --ignore-init-module-imports .
```

**5. Осмысленные сообщения коммитов**  
При добавлении нового кода командой
```bash
git commit -am "Msg"
```
или
```bash
git add /path/to/files
git commit -m "Msg"
```
в качестве `"Msg"` необходимо писать осмысленные сообщения.  
Чтобы придумывание сообщения для коммита не было проблемой, необходимо разделять свои изменения на логические составляющие. То есть не добавлять в один коммит все изменения сразу. Тогда будет легче описывать те изменения, которые добавляешь в коммит, например:
- Когда исправил падающие тесты
```bash
git commit -am "Fix failed tests"
```

- Когда Добавил новые константы в тестовое окружение
```bash
git commit -am "Add new constants into test.yml"
```

- Когда исправил опечатку в коде
```bash
git commit -am "Fix typo"
```

и так далее.
