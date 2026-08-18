"""
직업 분류 체계 시드 데이터.

출처: work.go.kr > 취업지원 > 취업가이드 > 직업정보 > 분류별 찾기
      (https://www.work.go.kr/consltJobCarpa/srch/jobInfoSrch/srchJobInfo.do)
수집일: 2026-07-29
수집 결과: 대분류 10개 / 중분류 35개 / 직업 538개

source_key는 해당 페이지의 DOM id다. 나중에 분류가 개편됐을 때
같은 키로 다시 긁어 대조할 수 있도록 함께 저장한다.

expected_job_count는 수집 당시 각 대분류의 직업 수. 재수집 후
이 값과 크게 달라지면 크롤러가 깨졌다는 신호로 쓴다.
"""

# (source_key, 대분류명, expected_job_count, [(중분류 source_key, 중분류명), ...])
TAXONOMY = [
    (
        "korSysJobA0",
        "경영·사무·금융·보험직",
        86,
        [
            ("korSubJobA01", "관리직(임원·부서장)"),
            ("korSubJobA02", "경영·행정·사무직"),
            ("korSubJobA03", "금융·보험직"),
        ],
    ),
    (
        "korSysJobA1",
        "연구직 및 공학 기술직",
        112,
        [
            ("korSubJobA11", "인문·사회과학 연구직"),
            ("korSubJobA12", "자연·생명과학 연구직"),
            ("korSubJobA13", "정보통신 연구개발직 및 공학기술직"),
            ("korSubJobA14", "건설·채굴 연구개발직 및 공학기술직"),
            ("korSubJobA15", "제조 연구개발직 및 공학기술직"),
        ],
    ),
    (
        "korSysJobA2",
        "교육·법률·사회복지·경찰·소방직 및 군인",
        33,
        [
            ("korSubJobA21", "교육직"),
            ("korSubJobA22", "법률직"),
            ("korSubJobA23", "사회복지·종교직"),
            ("korSubJobA24", "경찰·소방·교도직"),
            ("korSubJobA25", "군인"),
        ],
    ),
    (
        "korSysJobA3",
        "보건·의료직",
        39,
        [
            ("korSubJobA30", "보건·의료직"),
        ],
    ),
    (
        "korSysJobA4",
        "예술·디자인·방송·스포츠직",
        61,
        [
            ("korSubJobA41", "예술·디자인·방송직"),
            ("korSubJobA42", "스포츠·레크리에이션직"),
        ],
    ),
    (
        "korSysJobA5",
        "미용·여행·숙박·음식·경비·청소직",
        45,
        [
            ("korSubJobA51", "미용·예식 서비스직"),
            ("korSubJobA52", "여행·숙박·오락 서비스직"),
            ("korSubJobA53", "음식 서비스직"),
            ("korSubJobA54", "경호·경비직"),
            ("korSubJobA55", "돌봄 서비스직(간병·육아)"),
            ("korSubJobA56", "청소 및 기타 개인서비스직"),
        ],
    ),
    (
        "korSysJobA6",
        "영업·판매·운전·운송직",
        36,
        [
            ("korSubJobA61", "영업·판매직"),
            ("korSubJobA62", "운전·운송직"),
        ],
    ),
    (
        "korSysJobA7",
        "건설·채굴직",
        24,
        [
            ("korSubJobA70", "건설·채굴직"),
        ],
    ),
    (
        "korSysJobA8",
        "설치·정비·생산직",
        92,
        [
            ("korSubJobA81", "기계 설치·정비·생산직"),
            ("korSubJobA82", "금속·재료 설치·정비·생산직(판금·단조·주조·용접·도장 등)"),
            ("korSubJobA83", "전기·전자 설치·정비·생산직"),
            ("korSubJobA84", "정보통신 설치·정비직"),
            ("korSubJobA85", "화학·환경 설치·정비·생산직"),
            ("korSubJobA86", "섬유·의복 생산직"),
            ("korSubJobA87", "식품 가공·생산직"),
            ("korSubJobA88", "인쇄·목재·공예 및 기타 설치·정비·생산직"),
            ("korSubJobA89", "제조 단순직"),
        ],
    ),
    (
        "korSysJobA9",
        "농림어업직",
        10,
        [
            ("korSubJobA90", "농림어업직"),
        ],
    ),
]

TOTAL_EXPECTED_JOBS = sum(row[2] for row in TAXONOMY)  # 538
