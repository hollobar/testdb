"""창의성 교육 수강 관리 프로그램

구글 시트(또는 CSV 파일)의 수강 기록을 읽어, 아이별로 어떤 수업을 들었는지
한눈에 볼 수 있는 HTML 화면을 만든다.
학생정보 파일(보호자 연락처·주소 등)이 있으면 아이 이름을 눌러 따로 볼 수 있게 붙인다.

사용법
  python 수강관리.py 수강기록.csv                       # CSV 파일로 만들기
  python 수강관리.py 수강기록.csv --info 학생정보.csv    # 개인정보 파일을 지정해서 만들기
  python 수강관리.py "구글시트 주소"                     # 구글 시트에서 바로 가져오기
  python 수강관리.py --sample                          # 가상 데이터 500명으로 시험해 보기
  (뒤에 --no-open 을 붙이면 브라우저를 열지 않는다)
  --info 를 주지 않으면 이 폴더의 학생정보.csv 를 자동으로 찾는다.

만들어지는 파일 (결과/ 폴더) — 둘 다 직원 아이디·비밀번호로 잠긴다
  수강현황.html         개인정보 포함. 담당자만 본다.
  수강현황_공유용.html   개인정보를 뺀 판. 공유는 이 파일로 한다.

직원 계정: 직원/ 폴더에서 관리한다 (직원관리.py 참고).
  화면의 [회원가입] → 신청 파일 → 직원관리.bat으로 승인 → 이 프로그램을 다시 실행하면 로그인할 수 있다.
  직원/ 폴더는 절대 공유하지 않는다.

수강기록 형식: 수업 한 번(또는 수강 한 건)이 한 줄
  학생번호, 이름, 학년, 반, 수업명, 날짜
학생정보 형식: 아이 한 명이 한 줄. 학생번호(또는 이름·학년·반)로 수강기록과 연결한다.
  학생번호, 이름, 학년, 반, 보호자 이름, 보호자 연락처, 주소, ... (나머지 열은 모두 그대로 보여 준다)
"""

import base64
import csv
import hashlib
import io
import json
import os
import random
import re
import sys
import urllib.request
import webbrowser
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import 직원관리

# 시트의 열 이름이 다르면 여기만 고친다. (왼쪽: 프로그램 안 이름, 오른쪽: 시트에서 쓰는 이름 후보)
COLUMNS = {
    "id": ["학생번호", "번호", "ID"],          # 없어도 된다. 있으면 동명이인 구분에 쓴다.
    "name": ["이름", "성명", "학생이름"],
    "grade": ["학년"],
    "group": ["반", "반명"],
    "course": ["수업명", "수업", "프로그램"],
    "date": ["날짜", "수업일", "수강일"],
}
REQUIRED = ["name", "group", "course"]
GROUPS = ["씨앗반", "새싹반", "열매반"]

BASE = Path(__file__).resolve().parent
OUT_DIR = BASE / "결과"
TEMPLATE = BASE / "화면틀.html"
DEFAULT_INFO = BASE / "학생정보.csv"


# ---------- 데이터 읽기 ----------

def sheet_url_to_csv(url):
    """구글 시트 주소를 CSV 내려받기 주소로 바꾼다."""
    m = re.search(r"/spreadsheets/d/([\w-]+)", url)
    if not m:
        return url
    gid = re.search(r"[#&?]gid=(\d+)", url)
    return (f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv"
            + (f"&gid={gid.group(1)}" if gid else ""))


def read_text(source):
    if source.startswith("http"):
        url = sheet_url_to_csv(source)
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                raw = r.read()
        except Exception as e:
            sys.exit(f"구글 시트를 가져오지 못했습니다: {e}\n"
                     "시트 공유를 '링크가 있는 모든 사용자 - 뷰어'로 했는지 확인하거나,\n"
                     "파일 → 다운로드 → CSV로 받아 그 파일을 넣어 주세요.")
        if raw.lstrip().startswith(b"<"):
            sys.exit("CSV 대신 웹페이지가 왔습니다. 시트가 비공개일 수 있습니다. CSV로 내려받아 넣어 주세요.")
    else:
        raw = Path(source).read_bytes()
    for enc in ("utf-8-sig", "cp949"):       # 구글은 UTF-8, 엑셀에서 저장한 CSV는 CP949인 경우가 많다
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    sys.exit("파일 글자 인코딩을 알 수 없습니다. UTF-8 CSV로 저장해 주세요.")


def find_columns(header, required, what):
    cols = {}
    clean = [h.strip() for h in header]
    for key, names in COLUMNS.items():
        for n in names:
            if n in clean:
                cols[key] = clean.index(n)
                break
    missing = [COLUMNS[k][0] for k in required if k not in cols]
    if missing:
        sys.exit(f"{what}에 필요한 열이 없습니다: {', '.join(missing)}\n"
                 f"지금 열: {', '.join(clean)}\n"
                 "수강관리.py 위쪽 COLUMNS에 시트의 열 이름을 추가해 주세요.")
    return cols


def normalize_group(text):
    t = text.strip()
    if t and not t.endswith("반"):
        t += "반"
    return t


def normalize_date(text):
    t = text.strip()
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y. %m. %d.", "%Y. %m. %d", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(t, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return t


def student_key(rec):
    # 학생번호가 있으면 그것으로, 없으면 이름+학년+반으로 한 사람을 구분한다
    return rec["id"] or f'{rec["name"]}|{rec["grade"]}|{rec["group"]}'


def read_rows(text, required, what):
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        sys.exit(f"{what}가 비어 있습니다.")
    cols = find_columns(rows[0], required, what)
    get = lambda row, k: row[cols[k]].strip() if k in cols and cols[k] < len(row) else ""
    out = []
    for row in rows[1:]:
        rec = {k: get(row, k) for k in COLUMNS}
        rec["group"] = normalize_group(rec["group"])
        rec["grade"] = re.sub(r"\D", "", rec["grade"])
        out.append((rec, row))
    return rows[0], cols, out


def load_records(text):
    _, _, rows = read_rows(text, REQUIRED, "수강기록")
    records, skipped = [], 0
    for rec, _ in rows:
        if not rec["name"] or not rec["course"]:
            skipped += 1
            continue
        rec["date"] = normalize_date(rec["date"])
        records.append(rec)
    return records, skipped


def load_profiles(text):
    """학생정보 파일을 읽어 {학생 키: [[항목, 값], ...]} 로 돌려준다."""
    header, cols, rows = read_rows(text, ["name"], "학생정보")
    key_cols = set(cols.values())
    extra = [(i, h.strip()) for i, h in enumerate(header) if i not in key_cols and h.strip()]
    profiles = {}
    for rec, row in rows:
        if not rec["name"]:
            continue
        fields = [[label, row[i].strip() if i < len(row) else ""] for i, label in extra]
        # 한쪽 파일에만 학생번호가 있어도 연결되도록 두 가지 키로 등록한다
        # (이름·학년·반이 같은 아이가 둘 이상이면 이 키로는 연결하지 않는다 — 다른 아이 정보가 뜨지 않게)
        profiles[student_key(rec)] = fields
        nmg = student_key({**rec, "id": ""})
        if rec["id"]:
            profiles[nmg] = None if nmg in profiles else fields
    return profiles


# ---------- 집계 ----------

def build_data(records, source_label, profiles=None):
    students = {}
    for r in records:
        s = students.setdefault(student_key(r), {
            "id": r["id"], "name": r["name"], "grade": r["grade"], "group": r["group"],
            "courses": defaultdict(list),
        })
        s["courses"][r["course"]].append(r["date"])

    out_students, matched = [], 0
    for key, s in students.items():
        courses = [{"name": c, "count": len(d), "dates": sorted(x for x in d if x)}
                   for c, d in sorted(s["courses"].items())]
        st = {**s, "courses": courses, "total": sum(c["count"] for c in courses)}
        if profiles is not None:
            # 학생번호로 먼저 찾고, 없으면 이름·학년·반이 모두 같은 아이로 찾는다
            prof = profiles.get(key) or profiles.get(student_key({**s, "id": ""}))
            st["profile"] = prof
            matched += prof is not None
        out_students.append(st)
    out_students.sort(key=lambda s: (s["group"], s["grade"], s["name"]))

    course_people = Counter(c["name"] for s in out_students for c in s["courses"])
    group_people = Counter(s["group"] for s in out_students)
    dates = sorted(r["date"] for r in records if re.match(r"\d{4}-\d\d-\d\d", r["date"]))

    return {
        "source": source_label,
        "made": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "period": [dates[0], dates[-1]] if dates else None,
        "records": len(records),
        "hasProfiles": profiles is not None,
        "groups": [g for g in GROUPS if g in group_people] + sorted(set(group_people) - set(GROUPS)),
        "groupPeople": dict(group_people),
        "coursePeople": dict(course_people.most_common()),
        "students": out_students,
    }, matched


# ---------- 직원 로그인(암호화) ----------
# 화면 데이터는 무작위 열쇠로 암호화하고, 그 열쇠를 직원마다 각자의 비밀번호에서 만든 열쇠로 한 번 더 잠근다.
# 그래서 HTML 파일을 통째로 가져가도 아이디·비밀번호 없이는 내용을 읽을 수 없다.
# 직원 계정은 직원관리.py(직원/ 폴더)에서 관리한다.

def b64(b):
    return base64.b64encode(b).decode()


def id_hash(uid):
    return hashlib.sha256(("sugang:" + uid.strip().lower()).encode()).hexdigest()


def lock(data, accounts):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    data_key = AESGCM.generate_key(bit_length=256)
    iv = os.urandom(12)
    body = AESGCM(data_key).encrypt(iv, json.dumps(data, ensure_ascii=False).encode(), None)
    users = {}
    for a in accounts:
        kiv = os.urandom(12)
        wrapped = AESGCM(a["kek"]).encrypt(kiv, data_key + a["name"].encode(), None)
        users[id_hash(a["id"])] = {"salt": b64(a["salt"]), "iter": a["iter"], "iv": b64(kiv), "key": b64(wrapped)}
    return {"v": 2, "signupIter": 직원관리.PBKDF2_ITER, "users": users, "iv": b64(iv), "data": b64(body)}


def write_html(data, filename, accounts):
    OUT_DIR.mkdir(exist_ok=True)
    payload = json.dumps(lock(data, accounts))
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__VAULT__*/null", payload)
    out = OUT_DIR / filename
    out.write_text(html, encoding="utf-8")
    return out


def without_profiles(data):
    return {**data, "hasProfiles": False,
            "students": [{k: v for k, v in s.items() if k != "profile"} for s in data["students"]]}


# ---------- 가상 데이터 ----------

def make_sample(rec_path, info_path, n=500, seed=7):
    """시험용 가상 데이터. 실제 아이들·가족 정보가 아니다."""
    rnd = random.Random(seed)
    # 실제 사람·지역과 겹치지 않도록 이름은 번호로, 학교·주소는 기호로만 만든다
    dongs = "가나다라마바사아자차"
    schools = [f"{c}초등학교" for c in "ABCDE"]
    notes = ["", "", "", "", "땅콩 알레르기", "천식 있음, 흡입기 지참", "오후 4시 이후 조부모 하원", "안경 착용"]
    courses = {
        "씨앗반": ["그림책 상상놀이", "블록 쌓기 창작", "자연물 미술", "몸으로 표현하기"],
        "새싹반": ["코딩 놀이", "과학 실험", "메이커 공작", "창의 글쓰기", "보드게임 사고력"],
        "열매반": ["로봇 코딩", "발명 아이디어", "3D 프린팅", "토론과 발표", "과학 탐구 프로젝트"],
    }
    start = date(2026, 3, 7)
    with open(rec_path, "w", encoding="utf-8-sig", newline="") as f, \
         open(info_path, "w", encoding="utf-8-sig", newline="") as g:
        w, wi = csv.writer(f), csv.writer(g)
        w.writerow(["학생번호", "이름", "학년", "반", "수업명", "날짜"])
        wi.writerow(["학생번호", "이름", "학년", "반", "학교", "생년월일", "보호자 이름", "관계",
                     "보호자 연락처", "비상 연락처", "주소", "건강·특이사항", "사진 촬영 동의"])
        for i in range(1, n + 1):
            grade = rnd.randint(1, 6)
            group = GROUPS[(grade - 1) // 2]          # 1~2학년 씨앗, 3~4 새싹, 5~6 열매(가정)
            name = f"학생{i:03d}"
            sid = f"S{i:04d}"
            for course in rnd.sample(courses[group], rnd.randint(1, 3)):
                for _ in range(rnd.randint(1, 8)):
                    d = start + timedelta(weeks=rnd.randint(0, 30))
                    w.writerow([sid, name, grade, group, course, d.isoformat()])
            relation = rnd.choice(["어머니", "어머니", "아버지", "할머니"])
            birth = date(2026 - 7 - grade + 1, 1, 1) + timedelta(days=rnd.randint(0, 364))
            wi.writerow([sid, name, grade, group, rnd.choice(schools), birth.isoformat(),
                         f"보호자{i:03d}",
                         relation, f"010-0000-{rnd.randint(1000, 9999)}", f"010-0000-{rnd.randint(1000, 9999)}",
                         f"가상시 {rnd.choice(dongs)}동 {rnd.randint(1, 300)}",
                         rnd.choice(notes), rnd.choice(["동의", "동의", "미동의"])])


def main():
    argv = sys.argv[1:]
    info = None
    if "--info" in argv:
        i = argv.index("--info")
        if i + 1 >= len(argv):
            sys.exit("--info 뒤에 학생정보 파일 이름을 적어 주세요.")
        info = argv[i + 1]
        del argv[i:i + 2]
    args = [a for a in argv if not a.startswith("--")]
    flags = {a for a in argv if a.startswith("--")}

    if "--auto" in flags:                     # 실행.bat·직원관리.bat 용: 수강기록.csv가 있으면 그것, 없으면 가상 데이터
        if (BASE / "수강기록.csv").exists():
            args = [str(BASE / "수강기록.csv")]
        else:
            print("수강기록.csv 가 없어 가상 데이터로 화면을 만듭니다.")
            flags.add("--sample")
    if "--sample" in flags:
        source, info = str(BASE / "가상데이터.csv"), str(BASE / "가상학생정보.csv")
        make_sample(source, info)
        label = "가상데이터.csv (시험용 가상 데이터)"
    elif args:
        source = args[0]
        label = "구글 시트" if source.startswith("http") else Path(source).name
    else:
        sys.exit(__doc__)
    if info is None and DEFAULT_INFO.exists():
        info = str(DEFAULT_INFO)
    try:
        import cryptography  # noqa: F401
    except ImportError:
        sys.exit("암호화 패키지가 없습니다. 명령창에서 다음을 한 번 실행해 주세요.\n  python -m pip install cryptography")
    accounts = 직원관리.load_accounts("--sample" in flags)

    records, skipped = load_records(read_text(source))
    profiles = load_profiles(read_text(info)) if info else None
    data, matched = build_data(records, label, profiles)
    full = write_html(data, "수강현황.html", accounts)
    share = write_html(without_profiles(data), "수강현황_공유용.html", accounts)

    print(f"수강 기록 {data['records']}건, 학생 {len(data['students'])}명, 수업 {len(data['coursePeople'])}개")
    for g in data["groups"]:
        print(f"  {g}: {data['groupPeople'][g]}명")
    if skipped:
        print(f"이름이나 수업명이 비어 건너뛴 줄: {skipped}줄")
    if profiles is None:
        print("학생정보 파일이 없어 개인정보 없이 만들었습니다.")
    else:
        print(f"학생정보 연결: {matched}/{len(data['students'])}명 ({Path(info).name})")
        missing = [s["name"] for s in data["students"] if s.get("profile") is None]
        if missing:
            print(f"  학생정보를 찾지 못한 아이: {', '.join(missing[:10])}{' 외' if len(missing) > 10 else ''}")
    print(f"직원 계정 {len(accounts)}개로 잠갔습니다.")
    pend = [r for _, r, _ in 직원관리.pending_requests() if r]
    if pend:
        print(f"승인을 기다리는 가입 신청 {len(pend)}건: {', '.join(r['id'] for r in pend)} → 직원관리.bat")
    print(f"화면(개인정보 포함, 담당자용): {full}")
    print(f"화면(공유용, 개인정보 없음):   {share}")
    if "--no-open" not in flags:
        webbrowser.open(full.as_uri())


if __name__ == "__main__":
    main()
