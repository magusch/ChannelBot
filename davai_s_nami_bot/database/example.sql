CREATE TABLE IF NOT EXISTS "events" (
    "id" TEXT UNIQUE,
    "title" TEXT NOT NULL,
    "post_id" INTEGER UNIQUE,
    "date_from" TIMESTAMP,
    "date_to" TIMESTAMP
);



INSERT INTO events (id, title, post_id, date_from) 
VALUES (66, 'aaaa', 66, cast('2020-01-08 04:05:06' as TIMESTAMP));


INSERT INTO events (id, title, post_id, date_from, date_to) 
VALUES (88, 'bbbb', 88, cast('2020-03-08 04:05:06' as TIMESTAMP), cast('2020-03-09 04:05:06' as TIMESTAMP));

INSERT INTO events (id, title, post_id, date_from) 
VALUES (77, 'aaaa', 77, cast('2020-01-08 04:05:06' as TIMESTAMP));
