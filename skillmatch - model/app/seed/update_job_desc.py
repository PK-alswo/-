import sqlite3
import os
import re

# 경로 설정 (현재 스크립트 기준 절대 경로 활용)
base_dir = os.path.dirname(os.path.abspath(__file__))
source_db_path = os.path.join(base_dir, "../../jobs_only.db")
target_db_path = os.path.join(base_dir, "../../split_jobs.db")
pdf_path = os.path.join(base_dir, "한국고용직업분류_2025_해설서.pdf")

if os.path.exists(target_db_path):
    os.remove(target_db_path)

# 1. PDF 해설서에서 상세 직무 설명 추출 시도
pdf_descriptions = {}
if os.path.exists(pdf_path):
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            full_text = ""
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    full_text += text + "\n"
        
        matches = re.finditer(r'^(\d{4})\s+([^\n]+)\n(.*?)(?=\n\d{4}\s|\Z)', full_text, re.MULTILINE | re.DOTALL)
        for match in matches:
            job_name = match.group(2).strip()
            content = match.group(3)
            desc_match = re.search(r'주요\s*업무\s*\n(.*?)(?=\n\s*(?:■|※)?\s*(?:직업\s*예시|분류\s*시\s*유의사항)|\Z)', content, re.DOTALL)
            if desc_match:
                desc = desc_match.group(1).strip()
                desc = re.sub(r'\n+', ' ', desc)
                desc = desc.replace('·', '').strip()
                pdf_descriptions[job_name] = desc
    except Exception as e:
        print(f"PDF 파싱 중 안내: {e}")

# 2. 원본 DB에서 데이터 가져오기
if not os.path.exists(source_db_path):
    print(f"원본 DB 파일을 찾을 수 없습니다: {source_db_path}")
    exit()

source_conn = sqlite3.connect(source_db_path)
source_cursor = source_conn.cursor()

query = """
WITH RECURSIVE CategoryPath AS (
    SELECT id, name, level, parent_id,
           name AS level1_name,
           NULL AS level2_name,
           NULL AS level3_name
    FROM job_categories
    WHERE level = 1
    
    UNION ALL
    
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
source_conn.close()

# 1차 분류별 그룹화
grouped_data = {}
for row in rows:
    level1_name = row[0]
    cat_2nd = row[1] if row[1] else ""
    cat_3rd = row[2] if row[2] else ""
    job_name = row[3] if row[3] else ""
    desc = row[4]
    
    if not desc or desc.strip() == "" or desc == "None":
        matched_desc = None
        for p_job, p_desc in pdf_descriptions.items():
            if job_name.replace(" ", "") in p_job.replace(" ", ""):
                matched_desc = p_desc
                break
        if matched_desc:
            desc = matched_desc
        else:
            desc = f"{cat_2nd} 영역에서 {job_name}과(와) 관련된 전문적인 업무 및 관련 실무를 수행함."
            
    target_row = (cat_2nd, cat_3rd, job_name, desc)
    if level1_name not in grouped_data:
        grouped_data[level1_name] = []
    grouped_data[level1_name].append(target_row)

# 3. 새로운 DB 생성 및 job_01 ~ job_10 테이블 적재 (요청하신 컬럼명 반영)
target_conn = sqlite3.connect(target_db_path)
target_cursor = target_conn.cursor()

for idx, (level1_name, data) in enumerate(grouped_data.items(), start=1):
    if idx > 10:
        break
    table_name = f"job_{idx:02d}" # job_01 ~ job_10
    
    target_cursor.execute(f'''
    CREATE TABLE {table_name} (
        "ID" INTEGER PRIMARY KEY AUTOINCREMENT,
        "second_category" TEXT,
        "third_category" TEXT,
        "job" TEXT,
        "description" TEXT
    )
    ''')
    
    target_cursor.executemany(f'''
    INSERT INTO {table_name} ("second_category", "third_category", "job", "description")
    VALUES (?, ?, ?, ?)
    ''', data)

target_conn.commit()
target_conn.close()

print(f"성공! '{target_db_path}'에 job_01부터 job_10까지의 테이블이 요구하신 컬럼 구조(ID, second_category, third_category, job, description)로 생성되었습니다.")