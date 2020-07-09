CREATE TABLE IF NOT EXISTS "events" (
    "adress" TEXT,
    "category" TEXT,
    "date_from" TIMESTAMP,
    "date_to" TIMESTAMP,
    "id" INT NOT NULL UNIQUE,
    "place_name" TEXT,
    "post_text" TEXT,
    "poster_imag" TEXT,
    "price" TEXT,
    "title" TEXT NOT NULL,
    "url" TEXT NOT NULL UNIQUE,
    "is_registration_open" INTEGER,
    CHECK ("is_registration_open" = 0 or "is_registration_open" = 1)
);
