CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    nickname TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT '参与者',
    skills TEXT NOT NULL DEFAULT '',
    interests TEXT NOT NULL DEFAULT '',
    hours INTEGER NOT NULL DEFAULT 0,
    bio TEXT NOT NULL DEFAULT '',
    contact TEXT NOT NULL DEFAULT '',
    show_contact INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    needs TEXT NOT NULL,
    topics TEXT NOT NULL,
    min_hours INTEGER NOT NULL CHECK(min_hours BETWEEN 1 AND 168),
    capacity INTEGER NOT NULL CHECK(capacity BETWEEN 2 AND 20)
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'pending',
    UNIQUE(project_id, user_id)
);

CREATE TABLE IF NOT EXISTS memberships (
    project_id INTEGER NOT NULL REFERENCES projects(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY(project_id, user_id)
);

CREATE TABLE IF NOT EXISTS project_messages (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL DEFAULT 'chat' CHECK(kind IN ('chat', 'exit')),
    content TEXT NOT NULL CHECK(length(content) BETWEEN 1 AND 500),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_project_messages_project_id
    ON project_messages(project_id, id);
