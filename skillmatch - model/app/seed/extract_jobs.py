import sqlite3
import os

if os.path.exists("jobs_only.db"):
    os.remove("jobs_only.db")

source_conn = sqlite3.connect("skillmatch.db")
target_conn = sqlite3.connect("jobs_only.db")
target_cursor = target_conn.cursor()

target_cursor.executescript("""
CREATE TABLE job_categories (
    id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL, level INTEGER NOT NULL, 
    parent_id INTEGER, source_key VARCHAR(40), sort_order INTEGER NOT NULL,
    FOREIGN KEY(parent_id) REFERENCES job_categories (id) ON DELETE CASCADE
);
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY, name VARCHAR(200) NOT NULL UNIQUE, easy_name VARCHAR(120), 
    one_line_desc VARCHAR(300), category_id INTEGER NOT NULL, requires_cert BOOLEAN NOT NULL, 
    cert_note VARCHAR(300), is_recommendable BOOLEAN NOT NULL,
    FOREIGN KEY(category_id) REFERENCES job_categories (id) ON DELETE RESTRICT
);
""")

source_cursor = source_conn.cursor()

source_cursor.execute("SELECT id, name, level, parent_id, source_key, sort_order FROM job_categories")
target_cursor.executemany("INSERT INTO job_categories VALUES (?, ?, ?, ?, ?, ?)", source_cursor.fetchall())

source_cursor.execute("SELECT id, name, easy_name, one_line_desc, category_id, requires_cert, cert_note, is_recommendable FROM jobs")
target_cursor.executemany("INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?)", source_cursor.fetchall())

target_conn.commit()
source_conn.close()
target_conn.close()

print("직무 DB 추출 완료!")