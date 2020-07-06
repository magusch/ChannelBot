CREATE TABLE IF NOT EXISTS "events" (
    "adress" TEXT,
    "category" TEXT,
    "date" DATE,
    "date_from_to" TEXT,
    "id" INT NOT NULL UNIQUE,
    "place_name" TEXT,
    "post_text" TEXT,
    "poster_imag" TEXT,
    "price" TEXT,
    "title" TEXT NOT NULL,
    "title_date" TEXT,
    "url" TEXT NOT NULL UNIQUE
);
