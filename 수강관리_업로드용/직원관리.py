"""직원 계정 관리

직원/ 폴더 구성
  가입신청/    화면의 [회원가입]으로 받은 신청 파일(.json)을 여기에 넣는다
  승인/        승인된 직원. 수강관리.py가 이 직원들로 화면을 잠근다
  거절/        거절한 신청
  퇴사/        계정을 막은 직원 (기록은 남겨 둔다)
  직원계정.csv  (선택) 관리자가 직접 만드는 계정: 아이디, 비밀번호, 이름

사용법
  python 직원관리.py                    신청·승인 목록 보기
  python 직원관리.py 승인 아이디          가입신청/ 안의 신청을 승인
  python 직원관리.py 승인 파일.json       다른 곳에 있는 신청 파일을 바로 승인
  python 직원관리.py 거절 아이디
  python 직원관리.py 퇴사 아이디          로그인을 막는다 (다음 실행.bat 부터)
변경 뒤에는 실행.bat을 다시 실행해야 새 화면에 반영된다.

신청 파일에는 비밀번호 원문이 아니라 비밀번호에서 만든 열쇠가 들어 있다.
그래도 비밀번호만큼 중요한 파일이므로 직접 전달하고, 직원/ 폴더는 공유하지 않는다.
"""

import base64
import csv
import hashlib
import io
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
STAFF = BASE / "직원"
PENDING, APPROVED, REJECTED, LEFT = (STAFF / d for d in ("가입신청", "승인", "거절", "퇴사"))
CSV_FILE = STAFF / "직원계정.csv"
FORM_TEXT = "여기에비밀번호8자이상"
PBKDF2_ITER = 600_000          # 비밀번호를 하나씩 대입해 보는 공격을 느리게 만든다 (화면 쪽과 같아야 한다)
MIN_PW = 8
ID_RULE = re.compile(r"^[a-z0-9_.-]{3,20}$")
DEMO = {"id": "demo", "pw": "demo1234!", "name": "시험용 계정"}   # --sample 이고 계정이 하나도 없을 때만


def ensure_dirs():
    for d in (PENDING, APPROVED, REJECTED, LEFT):
        d.mkdir(parents=True, exist_ok=True)


def from_password(uid, pw, name):
    salt = os.urandom(16)
    return {"id": uid, "name": name, "salt": salt, "iter": PBKDF2_ITER,
            "kek": hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, PBKDF2_ITER, 32)}


def read_request(path):
    """신청 파일을 읽고 검사한다. 문제가 있으면 ValueError."""
    try:
        r = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        raise ValueError("신청 파일을 읽을 수 없습니다.")
    if r.get("type") != "sugang-signup":
        raise ValueError("수강현황 가입신청 파일이 아닙니다.")
    uid = str(r.get("id", "")).strip().lower()
    if not ID_RULE.match(uid):
        raise ValueError(f"아이디 '{uid}' 형식이 맞지 않습니다.")
    try:
        salt, kek = base64.b64decode(r["salt"]), base64.b64decode(r["kek"])
    except Exception:
        raise ValueError("신청 파일이 손상되었습니다.")
    if len(salt) != 16 or len(kek) != 32 or int(r.get("iter", 0)) < 100_000:
        raise ValueError("신청 파일이 손상되었습니다.")
    if not str(r.get("name", "")).strip():
        raise ValueError("이름이 비어 있습니다.")
    r["id"] = uid
    return r


def as_account(r):
    return {"id": r["id"], "name": r["name"].strip(), "salt": base64.b64decode(r["salt"]),
            "kek": base64.b64decode(r["kek"]), "iter": int(r["iter"])}


def load_csv_accounts(problems):
    if not CSV_FILE.exists():
        return []
    raw = CSV_FILE.read_bytes()
    text = next((raw.decode(e) for e in ("utf-8-sig", "cp949") if _decodes(raw, e)), "")
    rows = list(csv.reader(io.StringIO(text)))
    header = [h.strip() for h in rows[0]] if rows else []
    if "아이디" not in header or "비밀번호" not in header:
        problems.append("직원계정.csv 첫 줄에 '아이디', '비밀번호' 열이 있어야 합니다.")
        return []
    ci, cp = header.index("아이디"), header.index("비밀번호")
    cn = header.index("이름") if "이름" in header else None
    out = []
    for n, row in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in row):
            continue
        uid = (row[ci] if ci < len(row) else "").strip().lower()
        pw = row[cp] if cp < len(row) else ""
        name = (row[cn] if cn is not None and cn < len(row) else "").strip()
        if not uid:
            problems.append(f"직원계정.csv {n}번째 줄: 아이디가 비어 있습니다.")
        elif pw == FORM_TEXT:
            problems.append(f"직원계정.csv {n}번째 줄: '{uid}'의 비밀번호가 양식 예시 그대로입니다.")
        elif len(pw) < MIN_PW:
            problems.append(f"직원계정.csv {n}번째 줄: '{uid}'의 비밀번호가 {MIN_PW}자보다 짧습니다.")
        else:
            out.append({**from_password(uid, pw, name or uid), "from": "직원계정.csv"})
    return out


def _decodes(raw, enc):
    try:
        raw.decode(enc)
        return True
    except UnicodeDecodeError:
        return False


def load_accounts(sample=False):
    """화면을 잠글 계정 목록: 승인/ 폴더 + 직원계정.csv"""
    ensure_dirs()
    problems, accounts = [], []
    for f in sorted(APPROVED.glob("*.json")):
        try:
            accounts.append({**as_account(read_request(f)), "from": f"승인/{f.name}"})
        except ValueError as e:
            problems.append(f"승인/{f.name}: {e}")
    accounts += load_csv_accounts(problems)
    seen = {}
    for a in accounts:
        if a["id"] in seen:
            problems.append(f"아이디 '{a['id']}'가 겹칩니다: {seen[a['id']]}, {a['from']}")
        seen[a["id"]] = a["from"]
    if problems:
        sys.exit("직원 계정을 고쳐 주세요.\n  " + "\n  ".join(problems))
    if not accounts:
        if sample:
            print(f"승인된 직원이 없어 시험용 계정으로 잠급니다. 아이디 {DEMO['id']} / 비밀번호 {DEMO['pw']}")
            return [from_password(DEMO["id"], DEMO["pw"], DEMO["name"])]
        sys.exit("승인된 직원 계정이 없습니다.\n"
                 "  · 화면의 [회원가입]으로 신청 파일을 받아 '직원관리.bat'으로 승인하거나\n"
                 "  · 직원/직원계정.csv 에 아이디, 비밀번호, 이름을 직접 적어 주세요.")
    return accounts


def pending_requests():
    ensure_dirs()
    out = []
    for f in sorted(PENDING.glob("*.json")):
        try:
            out.append((f, read_request(f), None))
        except ValueError as e:
            out.append((f, None, str(e)))
    return out


# ---------- 명령 ----------

def find_pending(target):
    p = Path(target)
    if p.suffix.lower() == ".json" and p.exists():
        return p
    hits = [f for f, r, _ in pending_requests() if r and r["id"] == target.strip().lower()]
    if not hits:
        sys.exit(f"가입신청/ 폴더에 '{target}' 신청이 없습니다.")
    if len(hits) > 1:
        sys.exit(f"'{target}' 신청이 {len(hits)}건 있습니다. 파일 이름으로 지정해 주세요: "
                 + ", ".join(h.name for h in hits))
    return hits[0]


def move_unique(src, folder, name):
    dest = folder / name
    n = 2
    while dest.exists():
        dest = folder / f"{Path(name).stem}_{n}{Path(name).suffix}"
        n += 1
    src.replace(dest)
    return dest


def approve(target):
    src = find_pending(target)
    try:
        r = read_request(src)
    except ValueError as e:
        sys.exit(f"승인할 수 없습니다: {e}")
    if (APPROVED / f"{r['id']}.json").exists() or any(
            a["id"] == r["id"] for a in load_csv_accounts([])):
        sys.exit(f"아이디 '{r['id']}'는 이미 있습니다. 신청자에게 다른 아이디로 다시 신청하게 해 주세요.")
    r["approved"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    dest = APPROVED / f"{r['id']}.json"
    dest.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    if src.resolve().parent == PENDING.resolve():
        src.unlink()                 # 승인/으로 옮겨 적었으므로 신청함에서는 뺀다
    print(f"승인했습니다: {r['id']} ({r['name']})")
    if src.resolve().parent != PENDING.resolve():
        print(f"  원래 신청 파일({src})은 비밀번호만큼 중요합니다. 필요 없으면 지워 주세요.")


def reject(target):
    src = find_pending(target)
    dest = move_unique(src, REJECTED, src.name)
    print(f"거절했습니다: {dest.relative_to(STAFF)}")


def leave(uid):
    src = APPROVED / f"{uid.strip().lower()}.json"
    if not src.exists():
        sys.exit(f"승인/ 폴더에 '{uid}' 계정이 없습니다."
                 + (" 직원계정.csv에 있는 계정이면 그 줄을 지워 주세요." if CSV_FILE.exists() else ""))
    r = json.loads(src.read_text(encoding="utf-8"))
    r["left"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    src.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    dest = move_unique(src, LEFT, src.name)
    print(f"퇴사 처리했습니다: {r['id']} ({r.get('name', '')}) → {dest.relative_to(STAFF)}")
    print("  이미 나눠 준 화면 파일은 예전 계정으로 열리므로, 실행.bat으로 새로 만들어 바꿔 주세요.")


def show():
    ensure_dirs()
    pend = pending_requests()
    print(f"[가입 신청 {len(pend)}건]  (직원/가입신청)")
    for f, r, err in pend:
        if r:
            print(f"  {r['id']:<14} {r['name']:<8} {r.get('role', ''):<12} {r.get('phone', ''):<15} 신청 {r.get('requested', '')[:16]}")
        else:
            print(f"  {f.name}: {err}")
    appr = []
    for f in sorted(APPROVED.glob("*.json")):
        try:
            appr.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            appr.append({"id": f.name, "name": "(읽을 수 없음)"})
    print(f"\n[승인된 직원 {len(appr)}명]  (직원/승인)")
    for r in appr:
        print(f"  {r['id']:<14} {r.get('name', ''):<8} {r.get('role', ''):<12} {r.get('phone', ''):<15} 승인 {r.get('approved', '')}")
    if CSV_FILE.exists():
        n = len(load_csv_accounts([]))
        print(f"\n[직원계정.csv 계정 {n}개]")
    print(f"\n[퇴사 {len(list(LEFT.glob('*.json')))}명 · 거절 {len(list(REJECTED.glob('*.json')))}건]")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    a = sys.argv[1:]
    cmds = {"승인": approve, "approve": approve, "거절": reject, "reject": reject, "퇴사": leave, "remove": leave}
    if not a:
        show()
    elif len(a) == 1 and a[0].lower().endswith(".json"):
        approve(a[0])                      # 신청 파일을 직원관리.bat 위에 끌어다 놓은 경우
    elif len(a) == 2 and a[0] in cmds:
        cmds[a[0]](a[1])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
