CREATE TABLE IF NOT EXISTS trace_demo_items (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL
);

INSERT INTO trace_demo_items (id, name, category)
VALUES
    (1, 'fern', 'houseplant'),
    (2, 'cactus', 'succulent'),
    (3, 'monstera', 'tropical')
ON CONFLICT (id) DO NOTHING;
