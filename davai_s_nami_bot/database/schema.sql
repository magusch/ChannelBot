CREATE TABLE IF NOT EXISTS "dev_events" (
    "id" TEXT UNIQUE,
    "title" TEXT NOT NULL,
    "post_id" INTEGER,
    "event_date" TIMESTAMP,
    "date_to" TIMESTAMP
);


CREATE OR REPLACE FUNCTION date_from_to_date_to()
RETURNS TRIGGER AS
$$
BEGIN 
	UPDATE dev_events SET date_to=dev_events.date_from+ '2 hours' WHERE date_to is NULL;
	RETURN NEW;
END;
$$
LANGUAGE 'plpgsql';


CREATE TRIGGER empty_date_to AFTER INSERT ON dev_events 
FOR EACH ROW EXECUTE PROCEDURE date_from_to_date_to();