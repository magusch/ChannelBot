# Давай с нами бот

![Run tests](https://github.com/magusch/ChannelBot/workflows/Run%20tests/badge.svg)
[![CodeFactor](https://www.codefactor.io/repository/github/magusch/channelbot/badge?s=2dddd084faca7dfc56c595e695a9ecf05d98207c)](https://www.codefactor.io/repository/github/magusch/channelbot)

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
