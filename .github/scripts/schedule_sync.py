"""README ↔ Issue 자동 맞추기 (.github/workflows/schedule-sync.yml 이 돌림). Issue 두 개를 다룸:

  📅 살피 일정 체크      ↔ README <!-- 일정:시작 --> ~ <!-- 일정:끝 -->
  📋 피치 근거 보충 체크 ↔ README <!-- 피치근거:시작 --> ~ <!-- 피치근거:끝 -->   (plan/presentation/근거보충.md 4절)

- Issue 에서 체크박스를 누르면 (issues edited) → 두 Issue 의 지금 본문을 모두 README 의 제자리에 넣고
  bot 작업 공간 → dev PR → 바로 합치기 (사람이 누를 것 없음)
  (연달아 눌러 앞 실행이 취소돼도, 마지막 실행이 두 Issue 를 다 읽으니 빠지는 체크가 없음)
- README 가 dev 에서 바뀌면 (push) · 직접 돌리면 (workflow_dispatch) → README 각 부분을 Issue 본문으로
  (Issue 가 없으면 이때 만들고 맨 위에 고정)
- 내용이 같으면 아무것도 안 함 → 서로 계속 바꾸는 일 없음
- Issue 읽기 · 고치기는 GitHub 기본 토큰(ISSUE_TOKEN), README PR 합치기는 GH_TOKEN (개인 토큰엔 Issue 쓰기 권한이 없음)
"""
import json
import os
import re
import subprocess
import sys
import tempfile

SYNCS = [   # (Issue 제목, README 표시 이름)
    ("📅 살피 일정 체크", "일정"),
    ("📋 피치 근거 보충 체크", "피치근거"),
]
REPO = os.environ["REPO"]


def sh(*args, check=True):
    env = None
    if args[:2] == ("gh", "issue") and os.environ.get("ISSUE_TOKEN"):
        # 기본 토큰으로 고친 Issue 는 이 작업을 다시 깨우지 않아서, README ↔ Issue 가 서로 계속 바꾸는 일도 없음
        env = {**os.environ, "GH_TOKEN": os.environ["ISSUE_TOKEN"]}
    r = subprocess.run(args, capture_output=True, text=True, env=env)
    if check and r.returncode:
        print(r.stdout, r.stderr)
        sys.exit(r.returncode)
    return r.stdout.strip()


def norm(t):
    return (t or "").replace("\r\n", "\n").strip()


def readme_part(s, key):
    """(시작 표시 끝 위치, 끝 표시 위치) — 표시가 없으면 None."""
    m = re.search(rf"<!-- {key}:시작[^>]*-->\n", s)
    end = f"\n<!-- {key}:끝 -->"
    if not m or end not in s:
        return None
    return m.end(), s.index(end)


_issues = None


def find_issue(title):
    """제목이 같은 열린 Issue 중 가장 먼저 만든 것. 여러 개면 나머지는 닫음 (라벨은 안 붙는 경우가 있어 제목으로 찾음)."""
    global _issues
    if _issues is None:
        out = sh("gh", "issue", "list", "--repo", REPO, "--state", "open", "--json", "number,title,body", "--limit", "200")
        _issues = json.loads(out or "[]")
    items = sorted((i for i in _issues if i["title"].strip() == title), key=lambda i: i["number"])
    for dup in items[1:]:
        sh("gh", "issue", "close", str(dup["number"]), "--repo", REPO, "--comment",
           f"같은 Issue가 두 번 만들어져서 닫아요. 체크는 #{items[0]['number']} 에서 해 주세요.", check=False)
        print(f"중복 Issue #{dup['number']} 닫음")
    return items[0] if items else None


def to_issue(title, part):
    issue = find_issue(title)
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(part + "\n")
    if not issue:
        url = sh("gh", "issue", "create", "--repo", REPO, "--title", title, "--body-file", f.name)
        sh("gh", "issue", "pin", url, "--repo", REPO, check=False)
        print(f"[{title}] Issue 만듦: {url}")
    elif norm(issue["body"]) != norm(part):
        sh("gh", "issue", "edit", str(issue["number"]), "--repo", REPO, "--body-file", f.name)
        print(f"[{title}] Issue #{issue['number']} 를 README 에 맞춤")
    else:
        print(f"[{title}] Issue 와 README 가 같아요")


def to_readme():
    """두 Issue 의 지금 본문을 README 제자리에 → 바뀐 게 있으면 dev 로 PR · 합치기."""
    s = open("README.md", encoding="utf-8").read()
    changed = []
    for title, key in SYNCS:
        pos, issue = readme_part(s, key), find_issue(title)
        if not pos or not issue:
            continue
        a, b = pos
        if norm(s[a:b]) != norm(issue["body"]):
            s = s[:a] + norm(issue["body"]) + s[b:]
            changed.append(title)
    if not changed:
        print("README 와 Issue 가 같아요")
        return
    open("README.md", "w", encoding="utf-8").write(s)
    branch = f"bot/schedule-sync-{os.environ.get('GITHUB_RUN_ID', 'local')}"
    sh("git", "config", "user.name", "github-actions[bot]")
    sh("git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    sh("git", "checkout", "-b", branch)
    sh("git", "add", "README.md")
    sh("git", "commit", "-m", "docs : README 일정 체크 반영 (Issue 에서 자동)")
    sh("git", "push", "-u", "origin", branch)
    url = sh("gh", "pr", "create", "--repo", REPO, "--base", "dev", "--head", branch,
             "--title", "[docs] 일정 체크 자동 반영", "--body", f"Issue {', '.join(changed)} 에서 체크한 것을 README 에 자동으로 옮겼어요.")
    sh("gh", "pr", "merge", url.rsplit("/", 1)[-1], "--repo", REPO, "--merge", "--delete-branch")
    print(f"README 반영 · 합침: {url}")


if __name__ == "__main__":
    if sys.argv[1] == "issues":
        to_readme()
    else:
        s = open("README.md", encoding="utf-8").read()
        for title, key in SYNCS:
            pos = readme_part(s, key)
            if pos:
                to_issue(title, norm(s[pos[0]:pos[1]]))
            else:
                print(f"[{title}] README 에 <!-- {key}:시작 --> · <!-- {key}:끝 --> 표시가 없어 건너뜀")
