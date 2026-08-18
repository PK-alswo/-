/*
 * work.go.kr 직업정보 전체 수집 스크립트 (브라우저 콘솔용)
 *
 * 사용법
 *   1. https://www.work.go.kr/consltJobCarpa/srch/jobInfoSrch/srchJobInfo.do 접속
 *   2. F12 → Console 에 이 파일 전체를 붙여넣고 실행
 *   3. await collectAll()  → 완료되면 jobs.json 이 자동 다운로드됨
 *   4. python -m scripts.init_db --reset --jobs data/jobs.json
 *
 * 페이지가 별도 API 없이 firstSelect/secondSelect 로 DOM을 갱신하므로
 * 그 함수를 직접 호출하며 #srchResult 를 파싱한다.
 *
 * 주의: 대분류를 한 번에 다 돌리면 렌더러가 멈출 수 있다.
 *       아래처럼 sleep 을 충분히 두고, 필요하면 대분류별로 나눠 실행한다.
 */

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 현재 화면의 #srchResult 를 파싱해 [{group, job}] 반환 */
function parseResult() {
  const out = [];
  document
    .querySelectorAll("#srchResult div.column > ul.dot-list > li")
    .forEach((li) => {
      const group = (li.querySelector("div.font-bold")?.textContent || "").trim();
      li.querySelectorAll("ul.dash-list a").forEach((a) => {
        out.push({ group, job: a.textContent.trim() });
      });
    });
  return out;
}

/** 대분류 → 중분류 계층 구조만 먼저 수집 */
async function collectTaxonomy() {
  const majors = Array.from(document.querySelectorAll("#categoryOne a")).map(
    (a) => a.id
  );
  const tree = [];
  for (const mid of majors) {
    firstSelect(mid);
    await sleep(600);
    tree.push({
      key: mid,
      name: document.getElementById(mid).textContent.trim(),
      mids: Array.from(document.querySelectorAll("#categoryTwo a")).map((a) => ({
        key: a.id,
        name: a.textContent.trim(),
      })),
    });
  }
  return tree;
}

/** 전체 직업 수집 */
async function collectAll({ download = true } = {}) {
  const tree = await collectTaxonomy();
  const rows = [];

  for (const major of tree) {
    firstSelect(major.key);
    await sleep(600);
    for (const mid of major.mids) {
      secondSelect(mid.key);
      await sleep(800);
      const found = parseResult();
      found.forEach((r) =>
        rows.push({
          major: major.name,
          mid: mid.name,
          group: r.group,
          job: r.job,
        })
      );
      console.log(`${major.name} > ${mid.name}: ${found.length}건`);
    }
  }

  const unique = new Set(rows.map((r) => r.job));
  console.log(`총 ${rows.length}건 / 고유 직업 ${unique.size}개`);
  // 2026-07-29 기준 538건 / 538개

  if (download) {
    const blob = new Blob([JSON.stringify(rows, null, 1)], {
      type: "application/json",
    });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "jobs.json";
    a.click();
  }
  return rows;
}
