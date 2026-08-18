import sqlite3
import os

# 원본 DB와 새로 생성할 DB 경로 설정
source_db_path = "../../jobs_only.db" if os.path.exists("../../jobs_only.db") else "jobs_only.db"
target_db_path = "split_jobs.db"

# 기존에 생성된 타겟 DB가 있다면 초기화를 위해 삭제
if os.path.exists(target_db_path):
    os.remove(target_db_path)

source_conn = sqlite3.connect(source_db_path)
source_cursor = source_conn.cursor()

target_conn = sqlite3.connect(target_db_path)
target_cursor = target_conn.cursor()

# 1차~3차 분류와 직무명, 직무설명을 모두 가져오는 재귀 쿼리
query = """
WITH RECURSIVE CategoryPath AS (
    -- 1차 분류 (대분류)
    SELECT id, name, level, parent_id,
           name AS level1_name,
           NULL AS level2_name,
           NULL AS level3_name
    FROM job_categories
    WHERE level = 1
    
    UNION ALL
    
    -- 2차, 3차 분류를 재귀적으로 연결
    SELECT c.id, c.name, c.level, c.parent_id,
           p.level1_name,
           CASE WHEN c.level = 2 THEN c.name ELSE p.level2_name END,
           CASE WHEN c.level = 3 THEN c.name ELSE p.level3_name END
    FROM job_categories c
    JOIN CategoryPath p ON c.parent_id = p.id
)
SELECT 
    cp.level1_name,
    cp.level2_name,
    cp.level3_name,
    j.name,
    j.one_line_desc
FROM jobs j
JOIN CategoryPath cp ON j.category_id = cp.id
ORDER BY cp.level1_name, cp.level2_name, cp.level3_name, j.id;
"""

source_cursor.execute(query)
rows = source_cursor.fetchall()

# 1차 분류(대분류)별로 데이터 그룹화
grouped_data = {}
for row in rows:
    level1_name = row[0]
    # target_row: (2차 분류, 3차 분류, 직무명, 직무설명)
    target_row = (row[1], row[2], row[3], row[4])
    if level1_name not in grouped_data:
        grouped_data[level1_name] = []
    grouped_data[level1_name].append(target_row)

# 순서대로 10개의 테이블 생성 및 데이터 삽입 (enumerate 활용)
for idx, (level1_name, data) in enumerate(grouped_data.items()):
    table_name = f"job_{idx:02d}" # job_00, job_01 ...
        
    # 테이블 생성 쿼리 (IF NOT EXISTS 추가로 안전하게 생성)
    create_table_query = f'''
    CREATE TABLE IF NOT EXISTS {table_name} (
        "ID" INTEGER PRIMARY KEY AUTOINCREMENT,
        "2차" TEXT,
        "3차" TEXT,
        "직무" TEXT,
        "직무설명" TEXT
    )
    '''
    target_cursor.execute(create_table_query)
    
    # 데이터 삽입 쿼리
    insert_query = f'''
    INSERT INTO {table_name} ("2차", "3차", "직무", "직무설명")
    VALUES (?, ?, ?, ?)
    '''
    target_cursor.executemany(insert_query, data)

target_conn.commit()

source_conn.close()
target_conn.close()

print(f"성공! '{target_db_path}' 파일 내에 {len(grouped_data)}개의 테이블이 깔끔하게 생성되었습니다.")