CREATE TABLE IF NOT EXISTS "dev_events" (
    "id" TEXT UNIQUE,
    "title" TEXT NOT NULL,
    "post_id" INTEGER,
    "event_date" TIMESTAMP,
    "date_to" TIMESTAMP
);
