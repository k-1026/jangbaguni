"""README 일정 ↔ Issue "📅 살피 일정 체크" 자동 맞추기 (.github/workflows/schedule-sync.yml 이 돌림).

- Issue 에서 체크박스를 누르면 (issues edited)  → Issue 본문을 README 의 <!-- 일정:시작 --> ~ <!-- 일정:끝 --> 사이에 넣고
  bot 작업 공간 → dev PR → 바로 합치기 (사람이 누를 것 없음)
- README 가 dev 에서 바뀌면 (push) · 직접 돌리면 (workflow_dispatch) → README 일정 부분을 Issue 본문으로
  (Issue 가 없으면 이때 만들고 맨 위에 고정)
- 내용이 같으면 아무것도 안 함 → 서로 계속 바꾸는 일 없음
"""
import json
import os
import re
import subprocess
import sys
import tempfile

TITLE = "📅 살피 일정 체크"
START = re.compile(r"<!-- 일정:시작[^>]*-->\n")
END = "\n<!-- 일정:끝 -->"
REPO = os.environ["REPO"]


def sh(*args, check=True):
    env = None
    if args[:2] == ("gh", "issue") and os.environ.get("ISSUE_TOKEN"):
        # Issue 만들기 · 고치기는 GitHub 기본 토큰으로 (배포 담당자 개인 토큰엔 Issue 쓰기 권한이 없어 updateIssue 가 막혔음, 11/18)
        # 기본 토큰으로 고친 Issue 는 이 작업을 다시 깨우지 않아서, README ↔ Issue 가 서로 계속 바꾸는 일도 없음
        env = {**os.environ, "GH_TOKEN": os.environ["ISSUE_TOKEN"]}
    r = subprocess.run(args, capture_output=True, text=True, env=env)
    if check and r.returncode:
        print(r.stdout, r.stderr)
        sys.exit(r.returncode)
    return r.stdout.strip()


def norm(t):
    return (t or "").replace("\r\n", "\n").strip()


def readme_part():
    s = open("README.md", encoding="utf-8").read()
    m = START.search(s)
    if not m or END not in s:
        sys.exit("README 에 <!-- 일정:시작 --> · <!-- 일정:끝 --> 표시가 없어요")
    return s, m.end(), s.index(END)


def find_issue():
    """제목이 같은 열린 Issue 중 가장 먼저 만든 것. 여러 개면 나머지는 닫음 (라벨은 안 붙는 경우가 있어 제목으로 찾음)."""
    out = sh("gh", "issue", "list", "--repo", REPO, "--state", "open", "--json", "number,title,body", "--limit", "200")
    items = sorted((i for i in json.loads(out or "[]") if i["title"].strip() == TITLE), key=lambda i: i["number"])
    for dup in items[1:]:
        sh("gh", "issue", "close", str(dup["number"]), "--repo", REPO, "--comment",
           f"같은 일정 Issue가 두 번 만들어져서 닫아요. 체크는 #{items[0]['number']} 에서 해 주세요.", check=False)
        print(f"중복 Issue #{dup['number']} 닫음")
    return items[0] if items else None


def to_issue(part):
    issue = find_issue()
    body = part + "\n"
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(body)
    if not issue:
        url = sh("gh", "issue", "create", "--repo", REPO, "--title", TITLE, "--body-file", f.name)
        sh("gh", "issue", "pin", url, "--repo", REPO, check=False)
        print(f"Issue 만듦: {url}")
    elif norm(issue["body"]) != norm(part):
        sh("gh", "issue", "edit", str(issue["number"]), "--repo", REPO, "--body-file", f.name)
        print(f"Issue #{issue['number']} 를 README 에 맞춤")
    else:
        print("Issue 와 README 가 같아요")


def to_readme(body):
    s, a, b = readme_part()
    if norm(s[a:b]) == norm(body):
        print("README 와 Issue 가 같아요")
        return
    open("README.md", "w", encoding="utf-8").write(s[:a] + norm(body) + s[b:])
    branch = f"bot/schedule-sync-{os.environ.get('GITHUB_RUN_ID', 'local')}"
    sh("git", "config", "user.name", "github-actions[bot]")
    sh("git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    sh("git", "checkout", "-b", branch)
    sh("git", "add", "README.md")
    sh("git", "commit", "-m", "docs : README 일정 체크 반영 (Issue 에서 자동)")
    sh("git", "push", "-u", "origin", branch)
    url = sh("gh", "pr", "create", "--repo", REPO, "--base", "dev", "--head", branch,
             "--title", "[docs] 일정 체크 자동 반영", "--body", "Issue \"📅 살피 일정 체크\" 에서 체크한 것을 README 에 자동으로 옮겼어요.")
    sh("gh", "pr", "merge", url.rsplit("/", 1)[-1], "--repo", REPO, "--merge", "--delete-branch")
    print(f"README 반영 · 합침: {url}")


if __name__ == "__main__":
    event = sys.argv[1]
    if event == "issues":
        to_readme(os.environ.get("ISSUE_BODY", ""))
    else:
        s, a, b = readme_part()
        to_issue(norm(s[a:b]))
