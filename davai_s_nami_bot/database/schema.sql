CREATE TABLE IF NOT EXISTS "bot_events" (
    "id" TEXT UNIQUE,
    "title" TEXT NOT NULL,
    "post_id" INTEGER,
    "date_from" TIMESTAMP,
    "date_to" TIMESTAMP,
    "price" TEXT NOT NULL
);


CREATE OR REPLACE FUNCTION date_from_to_date_to()
RETURNS TRIGGER AS
$$
BEGIN
    UPDATE bot_events SET date_to=bot_events.date_from+ '2 hours' WHERE date_to is NULL;
    RETURN NEW;
END;
$$
LANGUAGE 'plpgsql';


CREATE TRIGGER empty_date_to AFTER INSERT ON bot_events
FOR EACH ROW EXECUTE PROCEDURE date_from_to_date_to();
