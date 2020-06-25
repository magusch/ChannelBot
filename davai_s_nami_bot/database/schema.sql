CREATE TABLE IF NOT EXISTS "events" (
    "title" TEXT NOT NULL,
    "date_start" CHAR(50),
    "place_name" TEXT,
    "post_text" CHAR(500),
    "adress" CHAR(50),
    "poster_imag" TEXT,
    "url" CHAR(50),
    "price" INT,
    "is_available" INT,
    /* Checks */
    CHECK ("is_available" = 0 or "is_available" = 1)
);
