# -*- coding: utf-8 -*-
"""新形式(2026-11-23〜)のミドリのレポートを、見出しの表記ゆれを許して読み取る。

新形式の中身:
  今日の要点 / 5資産の現在地 / 材料の読み方 / 注目する価格の節目 / 次の予定 / カレンダーの変更
  土曜はさらに 週間の値動き / 資金の流れ / 来週のシナリオ / 30日以内の重要日程

方針:
  * 数字は本文に書かれた文字列だけを使う。読み取れなければ「不明」にする(補完や推測はしない)。
  * 読み取れない部分は捨てずに、本文(Markdown)のまま折りたたみで出す。
  * 見出しの書き方(## / **太字** / 番号つき / 「:」つき)は問わない。
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------- 見出し

SECTION_PATTERNS = [
    ("long_schedule", r"(?:今後)?30\s*日(?:以内|間)?の?(?:重要)?日程|重要日程|30\s*日以内"),
    ("scenarios", r"(?:来週の)?シナリオ|上振れ.*下振れ"),
    ("flows", r"資金の流れ|資金フロー|投資部門別"),
    ("weekly", r"週間の値動き|今週の値動き|週間騰落|週間"),
    ("calendar", r"カレンダー(?:の)?(?:変更|更新|登録)?(?:なし|あり|は?ありません)?"),
    ("levels", r"(?:注目する)?価格の節目|節目|注目する価格"),
    ("news", r"材料の読み方|材料の見方|ニュースの読み方|材料"),
    ("assets", r"5\s*資産(?:の現在地)?|資産の現在地|現在地"),
    ("points", r"(?:今日の)?要点"),
    ("schedule", r"次の予定|今後3\s*日|3\s*日以内|直近の予定|予定"),
]
CORE = ("points", "assets", "news", "levels", "schedule", "calendar")
WEEKLY_KEYS = ("weekly", "flows", "scenarios", "long_schedule")

_NUM_PREFIX = re.compile(r"^(?:\d{1,2}\s*[.．)）、]|[①-⑩]|[A-Ea-e]\s*[.．)）])\s*")
_BOLD_HEAD = re.compile(r"^\*\*(.+?)\*\*\s*(.*)$")


def _classify(title: str):
    t = title.strip().strip("*").strip()
    t = _NUM_PREFIX.sub("", t).strip()
    t = re.sub(r"[:：]\s*$", "", t).strip()
    for key, pat in SECTION_PATTERNS:
        if re.match(r"^(?:" + pat + r")(?:\s*[（(][^)）]*[)）])?\s*(?:[:：].*)?$", t) or \
           re.match(r"^(?:" + pat + r")(?=[\s（(:：]|$)", t):
            return key, t
    return None, t


def parse_heading(line: str):
    """見出し行なら (key|None, タイトル, 同じ行の続き, '#の数' or 0, 太字か) を返す。"""
    raw = line.rstrip()
    if not raw.strip() or raw.startswith("    ") or raw.startswith("\t"):
        return None
    s = raw.strip()
    if s.startswith(("- ", "* ", "• ", "・", "|", ">")):
        return None
    hashes = 0
    m = re.match(r"^(#{1,6})\s*(.*)$", s)
    if m:
        hashes, s = len(m.group(1)), m.group(2)
    s_nonum = _NUM_PREFIX.sub("", s)
    bold = _BOLD_HEAD.match(s_nonum)
    if bold:
        key, title = _classify(bold.group(1))
        rest = bold.group(2).strip()
        # 「**今日の要点(3行):** 本文…」の本文は続きとして残す。見出しだけの太字行は rest が空。
        return key, title, rest, hashes, True
    if hashes:
        key, title = _classify(s_nonum)
        return key, title, "", hashes, False
    # 装飾なしの短い見出し行 (例: 「今日の要点(3行)」)
    if len(s_nonum) <= 30:
        key, title = _classify(s_nonum)
        if key:
            return key, title, "", 0, False
    return None


# ---------------------------------------------------------------- 共通の小物

def strip_md(s: str) -> str:
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", s)
    return s.strip()


_BULLET = re.compile(r"^\s*(?:[-*•・]|\d{1,2}[.．)）]|[①-⑩])\s+")


def _unbullet(line: str) -> str:
    return _BULLET.sub("", line, count=1).strip()


def logical_items(lines: list[str]) -> list[str]:
    """箇条書き(とその字下げ行)を1項目にまとめる。箇条書きでない行はそれぞれ1項目。"""
    items: list[str] = []
    cur = None
    for ln in lines:
        if not ln.strip():
            cur = None
            continue
        if ln.lstrip().startswith("|"):
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue
            items.append("\x00TABLE\x00" + "\x01".join(cells))
            cur = None
            continue
        if _BULLET.match(ln) and not ln.startswith(("    ", "\t")):
            cur = _unbullet(ln)
            items.append(cur)
        elif ln.startswith(("  ", "\t")) and items and cur is not None and not _BULLET.match(ln):
            items[-1] += " " + ln.strip()
            cur = items[-1]
        elif ln.startswith(("  ", "\t")) and _BULLET.match(ln) and items:
            # 入れ子の箇条書きは親の項目に追記 (改行で区切る)
            items[-1] += "\n" + _unbullet(ln)
        else:
            items.append(ln.strip())
            cur = None
    return items


def _table_cells(item: str):
    if item.startswith("\x00TABLE\x00"):
        return item[len("\x00TABLE\x00"):].split("\x01")
    return None


def is_table_header(cells) -> bool:
    j = " ".join(cells)
    return bool(re.search(r"資産|終値|前日比|日付|時刻|イベント|ニュース|材料|強気|弱気|区分|確度", j)) and not re.search(r"\d{1,3}(?:,\d{3})+|\d+\.\d+", j)


def _in_text(text: str, s: str) -> bool:
    if not s:
        return True
    if s in text:
        return True
    body = s.lstrip("+-")
    sign = s[0] if s[0] in "+-" else ""
    alts = [body] if not sign else [sign + body, "−" + body if sign == "-" else "＋" + body, "－" + body if sign == "-" else "+" + body, "▲" + body if sign == "-" else "+" + body]
    return any(a in text for a in alts) or (not sign and body in text)


# ---------------------------------------------------------------- 5資産

ASSETS = [
    ("日経225", r"日経\s*(?:平均|225)|Nikkei\s*225|Nikkei|N225"),
    ("金", r"金(?![利融属曜額])(?:先物|価格|相場)?|ゴールド|Gold|XAU"),
    ("ナスダック100", r"ナスダック\s*100|Nasdaq\s*-?\s*100|NASDAQ\s*-?\s*100|NQ|ナスダック|Nasdaq|NASDAQ"),
    ("原油", r"原油|WTI"),
    ("ビットコイン", r"ビットコイン|BTC|Bitcoin"),
]
SIGNS_NEG = "-−－▲△"
SIGNS_POS = "+＋"
NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
PCT_SIGNED = re.compile(r"(?<![\d/.,])([" + re.escape(SIGNS_POS + SIGNS_NEG) + r"])\s*(" + NUM + r")\s*(?:%|％)")
PCT_WORD = re.compile(r"(?<![\d/.,+\-−－▲△])(" + NUM + r")\s*(?:%|％)\s*(安|下落|下げ|低下|減|高|上昇|上げ|増)")
CHG_SIGNED = re.compile(r"(?<![\d/.,])([" + re.escape(SIGNS_POS + SIGNS_NEG) + r"])\s*(\$)?(" + NUM + r")(?!\d)(?!\s*(?:%|％))\s*(円|ドル|USD)?")
LEVEL = re.compile(r"(?<![\d/.,+\-−－▲△])(\$|US\$|USD\s*)?(" + NUM + r")(?!\d)(?![/\d])\s*(円|ドル|USD)?(?!\s*(?:%|％|月|日|時|週|年|営業日|bp|兆|億|万|倍))")


def _norm_sign(ch: str) -> str:
    return "-" if ch in SIGNS_NEG else "+"


def _pick_level(text: str):
    for m in LEVEL.finditer(text):
        num = m.group(2)
        digits = re.sub(r"\D", "", num)
        if "," not in num and "." not in num and len(digits) < 3:
            continue
        # 「11/21」「10:30」のような日付・時刻は除く
        tail = text[m.end():m.end() + 1]
        if tail == ":":
            continue
        pre = (m.group(1) or "")
        unit = m.group(3) or ""
        shown = ("$" if pre.strip().startswith(("$", "US$")) else ("USD " if pre.strip() == "USD" else "")) + num + unit
        return {"text": shown, "num": float(num.replace(",", "")), "unit": ("円" if unit == "円" else "ドル" if (unit in ("ドル", "USD") or pre.strip()) else "")}
    return None


def _row_from_text(label: str, rest: str, source: str) -> dict:
    row = {"label": label, "value": "", "change": "", "dir": "flat", "note": "", "unknown": False,
           "chgUnknown": False, "num": None, "unit": ""}
    lv = _pick_level(rest)
    if lv:
        row["value"], row["num"], row["unit"] = lv["text"], lv["num"], lv["unit"]
    pm = PCT_SIGNED.search(rest)
    if pm:
        sg = _norm_sign(pm.group(1))
        row["change"] = f"{sg}{pm.group(2)}%"
        row["dir"] = "dn" if sg == "-" else "up"
    else:
        pw = PCT_WORD.search(rest)
        if pw:
            sg = "-" if pw.group(2) in ("安", "下落", "下げ", "低下", "減") else "+"
            row["change"] = f"{sg}{pw.group(1)}%"
            row["dir"] = "dn" if sg == "-" else "up"
        else:
            cm = CHG_SIGNED.search(rest)
            if cm:
                sg = _norm_sign(cm.group(1))
                row["change"] = f"{sg}{cm.group(2) or ''}{cm.group(3)}{cm.group(4) or ''}"
                row["dir"] = "dn" if sg == "-" else "up"
    if "休場" in rest:
        row["note"] = "休場・前営業日" if "前営業日" in rest else "休場"
    nm = re.search(r"[（(]([^)）]*(?:\d{1,2}[:/]\d{1,2}|終値|時点|取得|JST|前営業日)[^)）]*)[)）]", rest)
    if nm and not row["note"]:
        row["note"] = nm.group(1).strip()
    if not row["value"] and not row["change"]:
        row["unknown"] = True
    elif "不明" in rest and not row["change"]:
        row["chgUnknown"] = True
    # 本文に無い文字列は出さない
    for k in ("value", "change"):
        if row[k]:
            core = re.sub(r"^(?:US\$|\$|USD\s*)", "", row[k])
            core = re.sub(r"(円|ドル|USD)$", "", core)
            if not _in_text(source, core):
                row[k] = ""
    if not row["value"] and not row["change"]:
        row["unknown"] = True
        row["note"] = ""
    return row


def _match_asset(text: str):
    for name, pat in ASSETS:
        m = re.match(r"^\**\s*(?:" + pat + r")\s*(?:[（(][^)）]*[)）])?\s*\**\s*[:：|\-–—]?\s*(.*)$", text)
        if m:
            # 「ナスダック」だけの行を100と見なすのは許容、ただし他資産の語頭に引っかからないよう長い語を優先済み
            return name, m.group(1)
    return None


def parse_assets(lines: list[str], source: str):
    items = logical_items(lines)
    rows: dict[str, dict] = {}
    used: set[int] = set()
    for idx, it in enumerate(items):
        cells = _table_cells(it)
        if cells is not None:
            if is_table_header(cells):
                continue
            label, rest = cells[0], " ".join(cells[1:])
            text = strip_md(label) + " " + strip_md(rest)
            ma = _match_asset(strip_md(label))
            if ma:
                name = ma[0]
                rest = " ".join(cells[1:])
            else:
                continue
        else:
            text = strip_md(it).replace("\n", " ")
            ma = _match_asset(it.replace("\n", " ").strip()) or _match_asset(text)
            if not ma:
                continue
            name, rest = ma
            rest = strip_md(rest)
        if name in rows:
            continue
        rows[name] = _row_from_text(name, rest, source)
        used.add(idx)
    out = []
    for name, _ in ASSETS:
        out.append(rows.get(name) or {"label": name, "value": "", "change": "", "dir": "flat", "note": "",
                                      "unknown": True, "chgUnknown": False, "num": None, "unit": ""})
    return out, used, items


# ---------------------------------------------------------------- 材料

TAG_RE = re.compile(r"[【\[（(]\s*(確定|観測・報道|観測|報道|推測|推定)\s*[】\]）)]")
BULL_RE = re.compile(r"^(?:強気に読む(?:なら|場合|と)?|強気の読み|強気(?:シナリオ|材料)?|買い材料|ブル)\s*[:：、,]?\s*")
BEAR_RE = re.compile(r"^(?:弱気に読む(?:なら|場合|と)?|弱気の読み|弱気(?:シナリオ|材料)?|売り材料|ベア)\s*[:：、,]?\s*")


def _tag_norm(t: str) -> str:
    if t in ("確定",):
        return "確定"
    if t in ("推測", "推定"):
        return "推測"
    return "観測"


def _find_tag(text: str):
    m = TAG_RE.search(text)
    if m:
        return _tag_norm(m.group(1)), (text[:m.start()] + text[m.end():]).strip()
    return "", text


def parse_news(lines: list[str]):
    body = "\n".join(lines)
    if re.search(r"新規材料なし|新しい材料(?:は)?(?:なし|ありません)", body) and not re.search(r"強気|弱気", body):
        return {"none": True, "items": [], "noneText": strip_md(body).strip()}
    # 表形式 (材料 | 強気 | 弱気 | 区分)
    table_rows = [logical for logical in logical_items(lines) if _table_cells(logical) is not None]
    if table_rows:
        head = None
        items = []
        for tr in table_rows:
            cells = _table_cells(tr)
            if head is None and any(re.search(r"強気", c) for c in cells) and any(re.search(r"弱気", c) for c in cells):
                head = cells
                continue
            if head is None:
                continue
            d = dict(zip(head, cells))
            title = bull = bear = tag = ""
            for h, v in d.items():
                if re.search(r"強気", h):
                    bull = v
                elif re.search(r"弱気", h):
                    bear = v
                elif re.search(r"区分|確度|種別|タグ", h):
                    tag = _tag_norm(strip_md(v).strip("【】[]()（） ")) if v.strip() else ""
                elif not title:
                    title = v
            t2, title = _find_tag(title)
            items.append({"title": strip_md(title), "tag": tag or t2, "body": [], "bull": bull, "bear": bear})
        if items:
            return {"none": False, "items": items}
    items = []
    cur = None
    target = None  # 'bull' | 'bear' | 'body'

    def new_item(title, lvl_hint=""):
        nonlocal cur, target
        tag, t = _find_tag(title)
        cur = {"title": strip_md(t).strip("：: "), "tag": tag, "body": [], "bull": "", "bear": ""}
        items.append(cur)
        target = "body"

    def handle_bb(plain):
        nonlocal target
        mb, me = BULL_RE.match(plain), BEAR_RE.match(plain)
        if not (mb or me):
            return False
        if cur is None:
            new_item("")
        if mb:
            rest = plain[mb.end():]
            split = re.search(r"[／/；;。]?\s*(?=弱気に読む|弱気[:：])", rest)
            if split and split.start() > 0:
                cur["bull"] = rest[:split.start()].strip(" 。;；／/")
                bear_rest = rest[split.end():]
                cur["bear"] = BEAR_RE.sub("", bear_rest, count=1).strip()
                target = "bear"
            else:
                cur["bull"] = rest.strip()
                target = "bull"
        else:
            cur["bear"] = plain[me.end():].strip()
            target = "bear"
        return True

    for ln in lines:
        if not ln.strip() or ln.lstrip().startswith("|"):
            continue
        indented = ln.startswith(("  ", "\t"))
        txt = _unbullet(ln.strip())
        plain = strip_md(txt)
        # 同じ行に強気/弱気が並ぶ形: 強気に読むなら…／弱気に読むなら…
        if handle_bb(plain):
            continue
        # 見出し的な行 = 新しい材料
        is_head = bool(re.match(r"^#{2,6}\s", ln.strip())) or bool(re.match(r"^\*\*[^*]+\*\*\s*[:：]?\s*$", txt)) \
            or (not indented and (_BULLET.match(ln) is not None) and cur is None) \
            or (not indented and _BULLET.match(ln) is not None and re.match(r"^(?:\d{1,2}[.．)）]|[①-⑩])\s", ln.strip()) is not None) \
            or (not indented and bool(TAG_RE.search(plain)) and target in (None, "body", "bull", "bear") and not (cur and not cur["bull"] and not cur["bear"] and not cur["body"]))
        if is_head and not (indented and cur is not None):
            t = re.sub(r"^#{2,6}\s*", "", txt)
            new_item(t)
            # 太字見出しの後ろに本文が続く場合 (**タイトル:** 事実…)
            m = re.match(r"^\*\*(.+?)\*\*\s*[:：]?\s*(.+)$", t)
            if m and m.group(2).strip():
                tag, tt = _find_tag(m.group(1))
                cur["title"] = strip_md(tt).strip("：: ")
                cur["tag"] = cur["tag"] or tag
                if not handle_bb(strip_md(m.group(2).strip())):
                    cur["body"].append(m.group(2).strip())
            continue
        if cur is None:
            new_item(txt)
            continue
        tag, t2 = _find_tag(txt)
        if tag and not cur["tag"]:
            cur["tag"] = tag
            txt = t2
        if target == "bull":
            cur["bull"] += (" " if cur["bull"] else "") + strip_md(txt)
        elif target == "bear":
            cur["bear"] += (" " if cur["bear"] else "") + strip_md(txt)
        else:
            cur["body"].append(txt)
    items = [i for i in items if i["title"] or i["body"] or i["bull"] or i["bear"]]
    return {"none": not items, "items": items}


# ---------------------------------------------------------------- 節目

DOWN_KW = re.compile(r"割っ?た|割れ|割る|割り込|割込|下回|下抜|下割|ブレイクダウン|切っ?た|切れ|下落した|下がっ?た|割った")
UP_KW = re.compile(r"回復|超え|上回|上抜|突破|戻し|奪回|復帰|上放れ|ブレイクアウト|上がっ?た|届いた")
PRICE = re.compile(r"(?<![\d/.,])(\$|US\$)?(" + NUM + r")(?!\d)\s*(円|ドル|USD|ポイント|pt|\$)?(?!\s*(?:%|％|月|日|時|週|年|営業日|bp))")
SUBJECTS = [("日経225", r"日経(?:平均|225)|日経"), ("金", r"金(?![利融属曜額])|ゴールド|XAU"), ("ナスダック100", r"ナスダック\s*100|ナスダック|Nasdaq\s*100|Nasdaq"),
            ("原油", r"原油|WTI"), ("ビットコイン", r"ビットコイン|BTC"), ("ドル円", r"ドル円")]


def _subject(text: str):
    for name, pat in SUBJECTS:
        m = re.search(pat, text)
        if m:
            return name, m.group(0)
    return "", ""


def _blank_subjects(cl: str) -> str:
    """「日経225」「ナスダック100」の数字を価格と取り違えないよう、主語の語を空白にして価格を探す。"""
    out = cl
    for _, pat in SUBJECTS:
        out = re.sub(pat, lambda m: " " * len(m.group(0)), out)
    return out


def parse_levels(lines: list[str], assets: list[dict]):
    items = logical_items(lines)
    groups: dict[tuple, dict] = {}
    order = []
    other = []
    for it in items:
        if _table_cells(it) is not None:
            c = _table_cells(it)
            if is_table_header(c):
                continue
            it = " ".join(c)
        text = strip_md(it).replace("\n", " ")
        why = ""
        wm = re.search(r"[（(]((?:根拠|理由|目安)[^)）]*)[)）]", text)
        if wm:
            why = wm.group(1).strip()
            text = (text[:wm.start()] + text[wm.end():]).strip()
        # 「日経225: 」のような頭の主語
        head_subject, head_word = _subject(text[:12])
        clauses = [c.strip() for c in re.split(r"(?<!\d),(?!\d{3})|[、。;；／]|(?<=\d),(?!\d)", text) if c.strip()]
        found_any = False
        subj_name, subj_word = head_subject, head_word
        for cl in clauses:
            pm = PRICE.search(_blank_subjects(cl))
            if not pm:
                continue
            num = pm.group(2)
            digits = re.sub(r"\D", "", num)
            if "," not in num and "." not in num and len(digits) < 3:
                continue
            d_m, u_m = DOWN_KW.search(cl), UP_KW.search(cl)
            if not d_m and not u_m:
                continue
            if d_m and u_m:
                direction = "dn" if d_m.start() < u_m.start() else "up"
            else:
                direction = "dn" if d_m else "up"
            s2, w2 = _subject(cl[:pm.start()])
            if s2:
                subj_name, subj_word = s2, w2
            unit = pm.group(3) or ""
            pre = pm.group(1) or ""
            shown = ("$" if pre else "") + num + unit
            nunit = "円" if unit == "円" else ("ドル" if (unit in ("ドル", "USD", "$") or pre) else unit)
            rest = cl[pm.end():]
            cond = re.sub(r"^[をがはにで]\s*", "", rest).strip()
            rung = {"dir": direction, "price": shown, "num": float(num.replace(",", "")), "text": cond or cl, "why": why}
            key = (subj_name or subj_word or "", nunit)
            if key not in groups:
                groups[key] = {"subject": subj_word and subj_name or subj_word or "", "asset": subj_name, "unit": nunit, "rungs": [], "current": None}
                order.append(key)
            groups[key]["rungs"].append(rung)
            found_any = True
        if not found_any and text.strip():
            other.append(it.replace("\n", " "))
    # 現在値 (5資産の本文にある数字だけを使う)
    byname = {a["label"]: a for a in assets}
    for key in order:
        g = groups[key]
        a = byname.get(g["asset"])
        if a and a.get("num") is not None and (not g["unit"] or not a.get("unit") or g["unit"] == a["unit"]):
            g["current"] = {"text": a["value"], "num": a["num"]}
        if g["asset"] == "":
            g["asset"] = ""
    return {"groups": [groups[k] for k in order], "other": other}


# ---------------------------------------------------------------- 予定

DATE_RE = re.compile(
    r"^(?:(?P<rel>今夜|今日|明日|明朝|明後日|今朝|あす)|(?:(?P<y>\d{4})[/年-])?(?P<m>\d{1,2})[/月](?P<d>\d{1,2})日?)"
    r"\s*(?:[（(](?P<dow>[日月火水木金土])(?:曜)?[)）])?\s*"
    r"(?:(?P<t1>\d{1,2}:\d{2})(?:\s*[〜~–\-]\s*(?P<t2>\d{1,2}:\d{2}))?|(?P<allday>終日|時刻未定|未定))?\s*[:：\-–—]?\s*(?P<rest>.*)$"
)


def parse_schedule(lines: list[str]):
    body = "\n".join(lines)
    items = []
    for it in logical_items(lines):
        c = _table_cells(it)
        if c is not None:
            if is_table_header(c):
                continue
            it = " ".join(x for x in c if x)
        txt = strip_md(it).replace("\n", " ").strip()
        if not txt:
            continue
        m = DATE_RE.match(txt)
        if m:
            date = m.group("rel") or f"{int(m.group('m'))}/{int(m.group('d'))}"
            time = m.group("t1") or ""
            if m.group("t2"):
                time += "〜" + m.group("t2")
            if not time and m.group("allday"):
                time = m.group("allday")
            title = m.group("rest").strip()
            if not time:
                tm = re.match(r"^(\d{1,2}:\d{2})(?:\s*[〜~–\-]\s*(\d{1,2}:\d{2}))?\s*[:：\-–—]?\s*(.*)$", title)
                if tm:
                    time = tm.group(1) + ("〜" + tm.group(2) if tm.group(2) else "")
                    title = tm.group(3).strip()
            items.append({"date": date, "dow": m.group("dow") or "", "time": time, "title": title or txt, "raw": it.replace("\n", " ")})
        else:
            items.append({"date": "", "dow": "", "time": "", "title": txt, "raw": it.replace("\n", " ")})
    none = (not items) or (len(items) == 1 and re.search(r"^(?:なし|予定なし|該当なし|特になし)", items[0]["title"]) is not None)
    return {"none": bool(none), "items": [] if none else items}


# ---------------------------------------------------------------- 土曜

UP_SC = re.compile(r"^(?:\**)(?:上振れ(?:シナリオ)?|強気シナリオ|アップサイド)")
DN_SC = re.compile(r"^(?:\**)(?:下振れ(?:シナリオ)?|弱気シナリオ|ダウンサイド)")


def parse_scenarios(lines: list[str]):
    cards = []
    cur = None
    rest = []
    for ln in lines:
        if not ln.strip():
            continue
        s = _unbullet(ln.strip()) if not ln.lstrip().startswith("#") else re.sub(r"^#+\s*", "", ln.strip())
        plain = strip_md(s)
        # 1行に上振れ・下振れが並ぶとき
        parts = re.split(r"(?=(?<![\w])下振れ(?:シナリオ)?\s*[:：])", plain) if (UP_SC.match(plain) and re.search(r"下振れ(?:シナリオ)?\s*[:：]", plain)) else [plain]
        for part in parts:
            kind = "up" if UP_SC.match(part) else ("down" if DN_SC.match(part) else "")
            if kind:
                m = re.match(r"^(上振れ(?:シナリオ)?|下振れ(?:シナリオ)?|強気シナリオ|弱気シナリオ|アップサイド|ダウンサイド)\s*(?:[（(]([^)）]*)[)）])?\s*[:：]?\s*(.*)$", part)
                title = m.group(1) if m else ("上振れシナリオ" if kind == "up" else "下振れシナリオ")
                body = (m.group(3) if m else "").strip()
                cur = {"kind": kind, "title": title, "sub": (m.group(2) or "") if m else "", "lines": [body] if body else []}
                cards.append(cur)
            elif cur is not None:
                cur["lines"].append(part)
            else:
                rest.append(part)
    ok = {c["kind"] for c in cards} >= {"up", "down"}
    return {"cards": cards if ok else [], "rest": rest if ok else [strip_md(l) for l in lines if l.strip()]}


# ---------------------------------------------------------------- 全体

def parse(markdown: str):
    """新形式なら構造を、そうでなければ None を返す。"""
    text = (markdown or "").replace("\r\n", "\n")
    lines = text.split("\n")
    sections = []
    preamble = []
    cur = None
    rec_level = None  # 認識した見出しが # 形式なら、その段数
    for ln in lines:
        h = parse_heading(ln)
        if h and h[0]:
            key, title, rest, hashes, bold = h
            if hashes and (rec_level is None or hashes < rec_level):
                rec_level = hashes if rec_level is None else min(rec_level, hashes)
            cur = {"key": key, "title": title, "lines": [rest] if rest else []}
            sections.append(cur)
            continue
        if h and not h[0] and h[3] and rec_level is not None and h[3] <= rec_level and sections:
            cur = {"key": "other", "title": h[1], "lines": [h[2]] if h[2] else []}
            sections.append(cur)
            continue
        if cur is None:
            preamble.append(ln)
        else:
            cur["lines"].append(ln)
    keys = [s["key"] for s in sections]
    if "points" not in keys or sum(1 for k in set(keys) if k in CORE and k != "points") < 2:
        return None
    # 同じ種類が2回出たら、後のものは「その他」にまわす
    seen = set()
    for s in sections:
        if s["key"] != "other" and s["key"] in seen:
            s["key"] = "other"
        seen.add(s["key"])
    for s in sections:
        while s["lines"] and not s["lines"][0].strip():
            s["lines"].pop(0)
        while s["lines"] and not s["lines"][-1].strip():
            s["lines"].pop()
    by = {s["key"]: s for s in sections if s["key"] != "other"}
    src = {k: "\n".join(v["lines"]) for k, v in by.items()}
    out = []
    assets_rows = None
    if "assets" in by:
        assets_rows, _, _ = parse_assets(by["assets"]["lines"], src["assets"])
    for s in sections:
        k = s["key"]
        d = {"key": k, "title": s["title"], "md": "\n".join(s["lines"]).strip()}
        L = s["lines"]
        if k == "points":
            items = [i for i in logical_items(L) if _table_cells(i) is None]
            pts = [i.replace("\n", " ") for i in items]
            if len(pts) == 1:
                sents = _sentences(pts[0])
                if len(sents) >= 2:
                    pts = sents
            d["lines"] = pts
        elif k == "assets":
            d["assets"] = assets_rows
        elif k == "news":
            d["news"] = parse_news(L)
        elif k == "levels":
            d["levels"] = parse_levels(L, assets_rows or [])
        elif k in ("schedule", "long_schedule"):
            d["schedule"] = parse_schedule(L)
        elif k == "calendar":
            d["text"] = " / ".join(strip_md(_unbullet(x)) for x in L if x.strip())
        elif k == "weekly":
            rows, used, items = parse_assets(L, d["md"])
            found = [r for r in rows if not r["unknown"]]
            d["assets"] = found
            rest_lines = [it.replace("\n", " ") for i, it in enumerate(items) if i not in used and _table_cells(it) is None]
            d["rest"] = rest_lines if found else []
        elif k == "scenarios":
            d["scenarios"] = parse_scenarios(L)
        out.append(d)
    pre = "\n".join(preamble).strip()
    return {"preamble": pre, "sections": out}


def _sentences(text: str):
    from summary import split_sentences
    return split_sentences(text)


def headline(v2) -> str:
    for s in v2["sections"]:
        if s["key"] == "points" and s.get("lines"):
            return strip_md(s["lines"][0])
    return ""


def validate(v2) -> list[str]:
    """ルーティンが後で確認できるよう、気になる点を文字列で返す。"""
    warn = []
    keys = [s["key"] for s in v2["sections"]]
    for need in ("points", "assets", "news", "levels", "schedule", "calendar"):
        if need not in keys:
            warn.append(f"見出しが見つからない: {need}")
    other = [s["title"] for s in v2["sections"] if s["key"] == "other"]
    if other:
        warn.append("未対応の見出し(本文のまま表示): " + " / ".join(other))
    for s in v2["sections"]:
        if s["key"] == "points" and len(s.get("lines", [])) != 3:
            warn.append(f"要点が3行ではない({len(s.get('lines', []))}行)")
        if s["key"] == "assets" and all(a["unknown"] for a in s["assets"]):
            warn.append("5資産がすべて不明(書式が読み取れていない可能性)")
        if s["key"] == "news" and not s["news"]["none"] and not any(i["bull"] or i["bear"] for i in s["news"]["items"]):
            warn.append("材料の強気/弱気が読み取れていない")
        if s["key"] == "levels" and not s["levels"]["groups"]:
            warn.append("節目の「割ったら/回復したら」が読み取れていない(本文のまま表示)")
    return warn
