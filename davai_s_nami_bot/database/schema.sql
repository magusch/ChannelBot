CREATE TABLE IF NOT EXISTS "events" (
    "id" INT NOT NULL UNIQUE,
    "date" DATE,
    "title" TEXT NOT NULL,
    "category" TEXT,
    "poster_imag" TEXT,
    "url" TEXT NOT NULL UNIQUE
);
