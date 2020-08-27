CREATE TABLE IF NOT EXISTS "events" (
    "adress" TEXT,
    "category" TEXT,
    "date_from" TIMESTAMP,
    "date_to" TIMESTAMP,
    "date_from_to" TEXT,
    "id" TEXT NOT NULL UNIQUE,
    "place_name" TEXT,
    "post_text" TEXT,
    "poster_imag" TEXT,
    "price" TEXT,
    "title" TEXT NOT NULL,
    "url" TEXT NOT NULL UNIQUE,
    "is_registration_open" INTEGER,
    "post_id" INTEGER UNIQUE,
    CHECK ("is_registration_open" = 0 or "is_registration_open" = 1)

);
