import os
from datetime import date, datetime, timedelta
from functools import lru_cache, partial
from typing import List

from notion.client import NotionClient

from .events import Event
from .logger import catch_exceptions, get_logger

DEFAULT_UPDATING_STRFTIME = "00:00"

notion_client = NotionClient(token_v2=os.environ.get("NOTION_TOKEN_V2"))
table1 = notion_client.get_collection_view(os.environ.get("NOTION_TABLE1_URL"))
table2 = notion_client.get_collection_view(os.environ.get("NOTION_TABLE2_URL"))
table3 = notion_client.get_collection_view(os.environ.get("NOTION_TABLE3_URL"))
posting_times_table = notion_client.get_collection_view(
    os.environ.get("NOTION_POSTING_TIMES_URL")
)
everyday_times = notion_client.get_collection_view(
    os.environ.get("NOTION_EVERYDAY_TIMES_URL")
)

notion_log = get_logger().getChild("NotionAPI")


def add_events(events, explored_date, table=None):
    table = table or table1

    for event in events:
        row = add_row(table)

        for property_name, value in event._asdict().items():
            set_property(
                row=row,
                property_name=property_name,
                value=value,
            )

        # event not contain "Explored date" and "Status" fields
        set_property(
            row=row,
            property_name="Explored date",
            value=explored_date,
        )

        # status only in table3
        if table is table3:
            set_property(
                row=row,
                property_name="Status",
                value="Ready to post",
            )


def remove_blank_rows():
    rows = (
        list(table1.collection.get_rows())
        + list(table2.collection.get_rows())
        + list(table3.collection.get_rows())
    )

    for row in rows:
        try:
            if row.get_property("Event_id") is None:
                remove_row(row)
        except TypeError as e:
            # to avoid notion bug
            if e.args[0] == "'NoneType' object is not iterable":
                remove_row(row)
            else:
                raise e


def remove_old_events(msk_date):
    """
    Removing events:
        - from table 1, where explored date > 2 days ago
        - from table 2, where explored date > 7 days ago
        - from tables 1, 2, 3, where date_from < today
    """
    remove_blank_rows()

    tables = (table1, table2, table3)
    check_funcs = (
        partial(check_for_move_to_table2, date=msk_date, days=2),
        partial(check_explored_date, date=msk_date, days=7),
        None,
    )

    for table, check_func in zip(tables, check_funcs):
        if table is table3:
            event_date_field = "To_date"
        else:
            event_date_field = "From_date"

        for row in table.collection.get_rows():
            event_date = row.get_property(event_date_field).start

            if not isinstance(event_date, datetime) and isinstance(event_date, date):
                event_date = datetime.combine(event_date, datetime.min.time())

            if event_date < msk_date:
                remove_row(row)

            elif check_func:
                check_func(row)


def in_past(record, target):
    return record.Date_from.start < target


def check_for_move_to_table2(record, date, days=None):
    if record.explored_date.start + timedelta(days=days) < date:
        move_row(record, table2)


def check_explored_date(record, date, days=None):
    if record.explored_date:
        if record.explored_date.start + timedelta(days=days) < date:
            remove_row(record)
    else:
        remove_row(record)


def move_approved():
    """
    Moving all approved events (with selected checkbox Approved)
    from table1 and table2 to table3.
    """
    rows = list(table1.collection.get_rows()) + list(table2.collection.get_rows())

    for row in rows:
        if row.Approved:
            move_row(row, table3)


@catch_exceptions()
def set_property(row, property_name, value):
    row.set_property(property_name, value)


@catch_exceptions()
def remove_row(row):
    row.remove()


@catch_exceptions()
def add_row(table, update_views=None):
    if update_views is not None:
        return table.collection.add_row(update_views=update_views)

    if table is table3:
        return table.collection.add_row(update_views=True)

    return table.collection.add_row(update_views=False)


@lru_cache()
def get_schema_properties(notion_block, property_name):
    return [
        property[property_name]
        for property in notion_block.collection.get_schema_properties()
    ]


def move_row(row, to_table, with_remove=True):
    if to_table is table3:
        # add at the end table
        new_row = add_row(to_table, update_views=True)
        set_property(new_row, "status", "Ready to post")

    else:
        new_row = add_row(to_table, update_views=False)

    table_tags = get_schema_properties(row, property_name="name")

    for tag in table_tags:
        # TODO: raised ValueError if property is None
        try:
            set_property(new_row, tag, row.get_property(tag))
        except:
            pass

    if with_remove:
        remove_row(row)


def next_event_to_channel():
    """
    Getting next event (namedtuple) from table 3 (from up to down).
    """
    rows = table3.collection.get_rows()
    event = None

    for row in rows:
        if row.status != "Posted":
            if row.status == "Ready to post":
                event = Event.from_notion_row(row)
                set_property(row, "status", "Posted")

            elif row.status == "Ready to skiped posting time":
                pass

            else:
                raise ValueError(f"Unavailable posting status: {row.status}")

            break

    return event


def get_new_events(events):
    existing_ids = list()
    for table in [table1, table2, table3]:
        for row in table.collection.get_rows():
            existing_ids.append(row.get_property("Event_id"))

    new_events = list()
    for event in events:
        if event.event_id not in existing_ids:
            new_events.append(event)

    return new_events


def not_published_count():
    count = 0

    for row in table3.collection.get_rows():
        count += row.status != "Posted"

    return count


def events_count():
    count = 0

    for table in [table1, table2, table3]:
        count += len(table.collection.get_rows())

    return count


def update_table_views():
    # 💫 some magic 💫
    # (see issue https://github.com/jamalex/notion-py/issues/92)
    for t in [table1, table2, table3]:
        print(t.collection.parent.views)


def get_weekday_posting_times(msk_today) -> List:
    return _get_times(msk_today, column="weekday")


def get_weekend_posting_times(msk_today) -> List:
    return _get_times(msk_today, column="weekend")


def _get_times(msk_today, column) -> List:
    """
    Return cell value from notion table:
    ("Wiki проекта" -> "Расписание выполнения задач"
    таблица "Постинг в канал")
    """
    times = list()
    for row in posting_times_table.collection.get_rows():
        hour, minute = map(int, row.get_property(column).split(":"))
        times.append(msk_today.replace(hour=hour, minute=minute))

    return times


def next_posting_time(reference):
    """
    Return next posting times according to notion table 3
    """
    posting_time = None

    for row in table3.collection.get_rows():
        if row.get_property("Status") == "Ready to post":
            if row.get_property("posting_datetime") is None:
                notion_log.warn(
                    "Unexcepteble warning: event in table 3 have not "
                    "posting datetime. Event title: {}.".format(row.Title)
                )
                # to next valid event
                continue

            notion_date = row.get_property("posting_datetime")

            if not hasattr(notion_date, "start"):
                notion_log.warn(
                    f"For event {row.get_property('Title')!r} "
                    "posting datetime has incorrect type. "
                    "Required 'NotionDate', received {notion_date.__class__.__name__!r}"
                )
                continue

            posting_time = notion_date.start

            if not isinstance(posting_time, datetime) and isinstance(posting_time, date):
                notion_log.warn(
                    f"For event {row.get_property('Title')!r} "
                    "posting datetime without hour and minute. "
                    "Please check event in table 3 (add hours and minutes)."
                )
                continue

            if posting_time < reference:
                notion_log.warn(
                    "Warning: event in table 3 have posting datetime in the past.\n"
                    f"Event title: {row.Title},\nevent id: {row.Event_id}"
                )
                # skip for events that posting time in past
                continue

            # posting_time is ok
            break

    return posting_time


def next_updating_time(reference):
    update_time = None
    with_warn = False

    for row in everyday_times.collection.get_rows():
        parameter_name = row.get_property("name")

        if parameter_name is not None and parameter_name == "update_events":
            everyday_str = row.get_property("everyday")
            if not isinstance(everyday_str, str):
                notion_log.warn(
                    "Incorrect type updating time in notion wiki. "
                    f"Required 'string', received {everyday_str.__class__.__name__!r}.\n"
                )
                with_warn = True
                everyday_str = DEFAULT_UPDATING_STRFTIME

            everyday_list = everyday_str.split(":")
            if len(everyday_list) != 2:
                notion_log.warn(
                    "Failed to parse everyday updating time. "
                    "Required time format is string like: HH:MM, "
                    f"received: {everyday_str!r}\n"
                )
                with_warn = True
                everyday_list = DEFAULT_UPDATING_STRFTIME.split(":")

            hour, minute = everyday_list

            if not hour.isdigit() or not minute.isdigit():
                notion_log.warn(
                    "Failed type casting for everyday updating time."
                    "Required type for hour and minute is 'int', "
                    f"received: {everyday_str!r}\n"
                )
                with_warn = True
                hour, minute = DEFAULT_UPDATING_STRFTIME.split(":")

            hour, minute = int(hour), int(minute)

            if not (0 <= hour <= 24) or not (0 <= minute <= 59):
                notion_log.warn(
                    "Incorrect hour or minute value!\nHour must be from 0 to 23, "
                    "minute must be from 0 to 59."
                )
                with_warn = True
                hour, minute = map(int, DEFAULT_UPDATING_STRFTIME.split(":"))

            if with_warn:
                notion_log.warn(
                    "Set update time as default: {DEFAULT_UPDATING_STRFTIME!r}"
                )

            update_time = reference.replace(hour=hour, minute=minute)

            # check for adding one day. Example:
            # if reference = 2020-01-01 16:00 and hour = 00, minute = 00
            # then, resulting update_time is 2020-01-02 00:00 (+ one day to reference)
            if reference.hour > hour or (
                reference.hour == hour and reference.minute > minute
            ):
                update_time += timedelta(days=1)

            break

    return update_time


def next_task_time(msk_today):
    task_time = None

    posting_time = next_posting_time(reference=msk_today)
    update_time = next_updating_time(reference=msk_today)

    if posting_time is None and update_time is None:
        # something bad happening
        raise ValueError("Don't found event for posting and updating time!")

    if posting_time is None:
        notion_log.warning("Don't event for posting! Continue with updating time.")
        task_time = update_time

    elif update_time is None:
        notion_log.warning("Don't found updating time! Continue with posting time.")
        task_time = posting_time

    elif update_time - msk_today < posting_time - msk_today:
        task_time = update_time

    else:
        task_time = posting_time

    return task_time


def is_monotonic(arr):
    return all([i > j for i, j in zip(arr[1:], arr[:-1])])


def check_posting_datetime():
    """
    Required nonempty posting_datetime field in all items in table3!
    """
    rows = [
        r
        for r in table3.collection.get_rows()
        if r.status in ["Ready to post", "Skip posting time"]
    ]
    posting_datetimes = [row.posting_datetime.start for row in rows]

    if not is_monotonic(posting_datetimes):
        for row, ptime in zip(rows, sorted(posting_datetimes)):
            set_property(row, "Posting_datetime", ptime)
