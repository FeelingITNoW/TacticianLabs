CREATE TABLE IF NOT EXISTS champions (
    champion_id INTEGER PRIMARY KEY,
    name TEXT
);

CREATE TABLE IF NOT EXISTS traits (
    trait_id INTEGER PRIMARY KEY,
    name TEXT
);

CREATE TABLE IF NOT EXISTS items (
    item_id INTEGER PRIMARY KEY,
    name TEXT
);


CREATE TABLE IF NOT EXISTS champion_stats (
    champion_id INTEGER PRIMARY KEY,
    win_rate FLOAT,
    top4_rate FLOAT,
    average_placement FLOAT
);

CREATE TABLE IF NOT EXISTS trait_stats (
    trait_id INTEGER PRIMARY KEY,
    win_rate FLOAT,
    top4_rate FLOAT,
    average_placement FLOAT
);

CREATE TABLE IF NOT EXISTS item_stats (
    item_id INTEGER PRIMARY KEY,
    win_rate FLOAT,
    top4_rate FLOAT,
    average_placement FLOAT
);