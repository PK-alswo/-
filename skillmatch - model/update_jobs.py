import sqlite3
import os

# DB 파일이 있는 정확한 경로 지정 (app/seed 폴더 기준 상위 폴더에 있는지 확인)
# 만약 jobs_only.db가 skillmatch 최상단 폴더에 있다면 아래 경로를 사용합니다.
db_path = "../../jobs_only.db" if os.path.exists("../../jobs_only.db") else "jobs_only.db"

# DB 연결
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# jobs 테이블의 모든 데이터의 is_recommendable 값을 1(True)로 일괄 변경
cursor.execute("UPDATE jobs SET is_recommendable = 1;")
conn.commit()

# 결과 출력
print(f"업데이트 완료! 총 {cursor.rowcount}개의 직업이 모두 추천 가능 상태로 변경되었습니다.")

conn.close()