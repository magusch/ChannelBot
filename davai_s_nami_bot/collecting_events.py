from escraper.parsers import Timepad

from .database import add2db


timepad_parser = Timepad()


def update_database():
    """
    Testing function that insert into database random event.
    """
    events = timepad_parser.events4day()

    add2db(events)
