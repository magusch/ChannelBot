CREATE TABLE IF NOT EXISTS "test_events" (
    "id" TEXT UNIQUE,
    "title" TEXT NOT NULL,
    "post_id" INTEGER,
    "date_from" TIMESTAMP,
    "date_to" TIMESTAMP
);


CREATE OR REPLACE FUNCTION date_from_to_date_to()
RETURNS TRIGGER AS
$$
BEGIN
    UPDATE test_events SET date_to=test_events.date_from+ '2 hours' WHERE date_to is NULL;
    RETURN NEW;
END;
$$
LANGUAGE 'plpgsql';


CREATE TRIGGER empty_date_to AFTER INSERT ON test_events
FOR EACH ROW EXECUTE PROCEDURE date_from_to_date_to();
