import sqlite3
import csv
import os

db_path = "../../jobs_only.db" if os.path.exists("../../jobs_only.db") else "jobs_only.db"

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 대분류, 중분류, 직무명, 직무설명을 추출하는 SQL 쿼리
query = """
WITH RECURSIVE CategoryPath AS (
    SELECT id, name, level, parent_id,
           name AS level1_name,
           NULL AS level2_name
    FROM job_categories
    WHERE level = 1
    
    UNION ALL
    
    SELECT c.id, c.name, c.level, c.parent_id,
           p.level1_name,
           CASE WHEN c.level = 2 THEN c.name ELSE p.level2_name END
    FROM job_categories c
    JOIN CategoryPath p ON c.parent_id = p.id
)
SELECT 
    cp.level1_name AS '대분류',
    cp.level2_name AS '중분류',
    j.name AS '직무명',
    j.one_line_desc AS '직무설명'
FROM jobs j
JOIN CategoryPath cp ON j.category_id = cp.id
ORDER BY cp.level1_name, cp.level2_name, j.id;
"""

cursor.execute(query)
rows = cursor.fetchall()

csv_filename = "final_job_db_v3.csv"
with open(csv_filename, 'w', encoding='utf-8-sig', newline='') as f:
    writer = csv.writer(f)
    # 4개 컬럼 헤더 작성
    writer.writerow(['대분류', '중분류', '직무명', '직무설명'])
    writer.writerows(rows)

conn.close()

print(f"'{csv_filename}' 파일 생성 완료! 대분류-중분류-직무명-직무설명 구조로 추출되었습니다.")