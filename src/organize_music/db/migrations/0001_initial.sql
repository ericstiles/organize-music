-- 0001_initial.sql -- the schema of PLAN §5, verbatim, plus the FTS5 sync
-- triggers that keep files_fts in step with files (external-content pattern).

CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);  -- library_root, created_at

CREATE TABLE files (
  file_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  path           TEXT,            -- relative to library root, exactly as on disk; NULL iff gone
  path_key       TEXT,            -- NFC(path).casefold(); exFAT collision key; NULL iff gone
  last_path      TEXT NOT NULL,   -- kept after the file is gone
  status         TEXT NOT NULL CHECK (status IN ('present','missing','changed','gone')),
  kind           TEXT NOT NULL CHECK (kind IN ('audio','art')),  -- art: jpg jpeg png gif bmp webp
  size           INTEGER NOT NULL,
  mtime_ns       INTEGER NOT NULL,
  ext            TEXT NOT NULL,
  raw_tags       TEXT, read_error TEXT, duration_seconds REAL, bitrate_kbps INTEGER,
  artist, artist_src TEXT NOT NULL, album_artist, album_artist_src TEXT NOT NULL,
  album, album_src TEXT NOT NULL, title, title_src TEXT NOT NULL,
  track_number, track_number_src TEXT NOT NULL, disc_number, disc_number_src TEXT NOT NULL,
  year, year_src TEXT NOT NULL, genre, genre_src TEXT NOT NULL,
  audio_hash     TEXT,
  hash_kind      TEXT CHECK (hash_kind IN ('audio','file')),
  hash_size      INTEGER, hash_mtime_ns INTEGER,
  row_version    INTEGER NOT NULL DEFAULT 1,
  first_seen_at  TEXT NOT NULL, updated_at TEXT NOT NULL,
  CHECK ((status = 'gone') = (path IS NULL)),
  CHECK ((path IS NULL) = (path_key IS NULL)),
  CHECK ((audio_hash IS NULL) = (hash_kind IS NULL))
);
CREATE UNIQUE INDEX files_path_key ON files(path_key) WHERE path_key IS NOT NULL;
CREATE INDEX files_hash ON files(hash_kind, audio_hash) WHERE audio_hash IS NOT NULL;
CREATE INDEX files_status ON files(status);
CREATE INDEX files_folder ON files(kind, path) WHERE path IS NOT NULL;  -- "audio left in folder?"
CREATE INDEX files_artist ON files(artist COLLATE NOCASE);
CREATE INDEX files_album  ON files(album  COLLATE NOCASE);
CREATE INDEX files_title  ON files(title  COLLATE NOCASE);
CREATE VIEW songs AS
  SELECT hash_kind, audio_hash, COUNT(*) AS copies, SUM(size) AS total_size
  FROM files WHERE kind = 'audio' AND status <> 'gone' AND audio_hash IS NOT NULL
  GROUP BY hash_kind, audio_hash;

CREATE VIRTUAL TABLE files_fts USING fts5(
  path, artist, album, title, content='files', content_rowid='file_id',
  tokenize='unicode61 remove_diacritics 2');

-- FTS5 external-content sync triggers (PLAN §5 "plus AFTER INSERT/UPDATE/DELETE
-- triggers on files keeping files_fts in sync"). The standard external-content
-- shape: an INSERT refreshes the index from the new row; a DELETE and the old
-- half of an UPDATE remove the stale copy with the 'delete' command, and the
-- new half of an UPDATE re-inserts the new copy.
CREATE TRIGGER files_ai AFTER INSERT ON files BEGIN
  INSERT INTO files_fts(rowid, path, artist, album, title)
    VALUES(NEW.file_id, NEW.path, NEW.artist, NEW.album, NEW.title);
END;
CREATE TRIGGER files_ad AFTER DELETE ON files BEGIN
  INSERT INTO files_fts(files_fts, rowid, path, artist, album, title)
    VALUES('delete', OLD.file_id, OLD.path, OLD.artist, OLD.album, OLD.title);
END;
CREATE TRIGGER files_au AFTER UPDATE ON files BEGIN
  INSERT INTO files_fts(files_fts, rowid, path, artist, album, title)
    VALUES('delete', OLD.file_id, OLD.path, OLD.artist, OLD.album, OLD.title);
  INSERT INTO files_fts(rowid, path, artist, album, title)
    VALUES(NEW.file_id, NEW.path, NEW.artist, NEW.album, NEW.title);
END;

CREATE TABLE batches (
  batch_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  kind         TEXT NOT NULL CHECK (kind IN ('rename','edit','undo','quarantine')),
  state        TEXT NOT NULL CHECK (state IN ('draft','confirmed','running','completed',
                 'completed_with_errors','stopped','cancelled','discarded')),
  description  TEXT NOT NULL,
  request_json TEXT NOT NULL,     -- the validated request that produced the preview
  undo_of      INTEGER REFERENCES batches(batch_id),
  total INTEGER NOT NULL DEFAULT 0, succeeded INTEGER NOT NULL DEFAULT 0,
  failed INTEGER NOT NULL DEFAULT 0, skipped INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, confirmed_at TEXT, finished_at TEXT
);

CREATE TABLE operations (
  op_id         INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id      INTEGER NOT NULL REFERENCES batches(batch_id),
  file_id       INTEGER NOT NULL REFERENCES files(file_id),
  unit_seq      INTEGER NOT NULL,   -- one unit = all steps for one file
  step_seq      INTEGER NOT NULL,   -- retag before move within a unit
  kind          TEXT NOT NULL CHECK (kind IN ('move','retag')),
  state         TEXT NOT NULL CHECK (state IN ('planned','intent','staged','parked','applied',
                  'committed','failed','skipped','needs_attention')),
  expect_path TEXT NOT NULL, expect_size INTEGER NOT NULL,
  expect_mtime_ns INTEGER NOT NULL, expect_row_version INTEGER NOT NULL,
  params_json   TEXT NOT NULL,      -- per kind, §6.2 / §6.3
  result_json   TEXT,
  error_code    TEXT, error_detail TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE (batch_id, unit_seq, step_seq)
);
CREATE UNIQUE INDEX operations_one_active_per_file ON operations(file_id)
  WHERE state IN ('intent','staged','parked','applied');
CREATE INDEX operations_file ON operations(file_id, op_id);

CREATE TABLE events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_id  INTEGER NOT NULL REFERENCES files(file_id),
  kind     TEXT NOT NULL CHECK (kind IN ('discovered','changed','missing','returned',
             'moved_externally','forgotten','rehashed')),
  detail_json TEXT NOT NULL, at TEXT NOT NULL
);

CREATE TABLE jobs (
  job_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  kind     TEXT NOT NULL CHECK (kind IN ('scan','hash','batch','recover')),
  state    TEXT NOT NULL CHECK (state IN ('queued','running','paused','succeeded','failed',
             'cancelled','interrupted')),
  batch_id INTEGER REFERENCES batches(batch_id),
  progress_done INTEGER NOT NULL DEFAULT 0, progress_total INTEGER,
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  result_json TEXT, error_code TEXT, error_detail TEXT,
  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT
);
