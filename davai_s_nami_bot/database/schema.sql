CREATE TABLE IF NOT EXISTS "dev_events" (
    "id" TEXT UNIQUE,
    "title" TEXT NOT NULL,
    "post_id" INTEGER UNIQUE,
    "event_date" TIMESTAMP
);
