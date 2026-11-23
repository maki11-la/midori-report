# -*- coding: utf-8 -*-
"""レポート本文から「今日の一言」「短い結論」「主要な数字カード」を取り出す。

数字は本文にそのまま書かれている文字列だけを使う。見つからないものは出さない
（推測や補完はしない）。build.py から使われ、結果は index.html に埋め込まれる。
"""
from __future__ import annotations

import re

OPEN = "（(「『［["
CLOSE = "）)」』］]"

SIGN_NEG = "-−－▲△"
SIGN_POS = "+＋"
NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
# 符号つきの変化率 (例: -7.70%, +0.71%, 約-14%)
PCT_RE = re.compile(r"(?<![\d/.,])([" + re.escape(SIGN_POS + SIGN_NEG) + r"])(" + NUM + r")\s*(?:%|％)")
# 符号つきの変化幅 (例: (-561.25), +419.93円)
CHG_RE = re.compile(r"(?<![\d/.,])([" + re.escape(SIGN_POS + SIGN_NEG) + r"])(" + NUM + r")(?![\d,]*\s*(?:%|％|bp|兆|億|万|倍|月|日|時|週|年))(円|ドル|ポイント)?")
# 符号なしの水準 (例: 56,436.65円, 159.35円, 24,429.89, 35.89)
LEVEL_RE = re.compile(r"(?<![\d/.,\-−－+＋▲△])(" + NUM + r")(?!\d)(?!\.\d)(?![\d,]*\s*(?:%|％|bp|兆|億|万|倍|月|日|時|週|年|号|社|銘柄|件|人|株|回|営業日|割))(?!円[安高下上]|円?幅|ドル[安高])(円|ドル)?(?!台)")

BAD_CTX = re.compile(r"売上|利益|粗利|EPS|決算|前年|前期|通期|予想比|ガイダンス|配当|寄与|時価総額|出来高|売買代金|目標株価")

# (ラベル, 名前の正規表現, 種類)
# kind: idx = 指数/個別株 (変化率を主役に), lvl = 水準を主役に
METRICS = [
    ("日経平均", r"日経(?:平均|225)(?!先物)(?!の?夜間)", "idx"),
    ("TOPIX", r"TOPIX", "idx"),
    ("Nasdaq", r"(?i:nasdaq)(?!\s?100)|ナスダック(?!100)", "idx"),
    ("S&P500", r"S&P\s?500|S＆P\s?500", "idx"),
    ("ダウ", r"ダウ(?:平均)?(?!ン)", "idx"),
    ("SOX", r"SOX|半導体指数", "idx"),
    ("NVIDIA", r"NVIDIA|エヌビディア", "idx"),
    ("ドル円", r"ドル円", "fx"),
    ("先物", r"(?:大阪取引所の)?夜間先物|日経(?:平均|225)先物|CME日経(?:平均|225)先物", "fut"),
]
MAX_WINDOW = 80
DEBUG = False


def split_sentences(text: str) -> list[str]:
    out, buf, depth = [], [], 0
    for ch in text:
        buf.append(ch)
        if ch in OPEN:
            depth += 1
        elif ch in CLOSE:
            depth = max(0, depth - 1)
        elif ch == "。" and depth == 0:
            s = "".join(buf).strip()
            if s.count("**") % 2 == 0:
                out.append(s)
                buf = []
    rest = "".join(buf).strip()
    if rest:
        if out and rest.count("**") % 2 == 1:
            out[-1] += rest
        else:
            out.append(rest)
    return out


def _strip_marker(line: str) -> str:
    return re.sub(r"^\s*(?:\d+[.．)]|[-*・])\s+", "", line).strip()


def conclusion_parts(r: dict) -> dict:
    cf = (r.get("conclusion_full") or r.get("conclusion") or "").replace("\r\n", "\n").strip()
    lines = [l for l in cf.split("\n") if l.strip()]
    is_list = len(lines) > 1 and all(re.match(r"^\s*(?:\d+[.．)]|[-*・])\s+", l) for l in lines)
    if is_list:
        items = [_strip_marker(l) for l in lines]
        first = split_sentences(items[0])
        later_items = items[1:]
    else:
        items = None
        first = split_sentences(lines[0]) if lines else []
        later_items = lines[1:]
    if not first:
        return {"headline": "", "lead": "", "rest": ""}
    head = first[0]
    used = 1
    total = len(head)
    # 2〜3文まで、合計が長くなりすぎない範囲で見せる
    while used < len(first) and used < 3:
        nxt = first[used]
        if total + len(nxt) > 170 and used >= 2:
            break
        if total + len(nxt) > 260:
            break
        total += len(nxt)
        used += 1
    lead = "".join(first[1:used])
    rest_sentences = "".join(first[used:])
    rest_blocks = []
    if rest_sentences:
        rest_blocks.append(rest_sentences)
    if is_list:
        rest_blocks += ["- " + i for i in later_items]
        rest = ("\n\n".join(rest_blocks[:1]) + ("\n\n" if rest_blocks[:1] and later_items else "") + "\n".join(rest_blocks[1:])).strip() if rest_blocks else ""
    else:
        rest_blocks += later_items
        rest = "\n\n".join(rest_blocks).strip()
    return {"headline": head, "lead": lead, "rest": rest}


def _norm_sign(s: str) -> str:
    if s in SIGN_NEG:
        return "-"
    return "+"


def _window(text: str, start: int, names_re: re.Pattern) -> str:
    """名前の直後から、文の終わり・次の指標名の手前まで。括弧の外の読点でも切る。"""
    depth = 0
    end = min(len(text), start + MAX_WINDOW)
    for i in range(start, end):
        ch = text[i]
        if ch in OPEN:
            depth += 1
        elif ch in CLOSE:
            depth = max(0, depth - 1)
        elif ch in "。\n" or (ch == "、" and depth == 0):
            end = i
            break
    w = text[start:end]
    m = names_re.search(w)
    if m:
        w = w[: m.start()]
    return w


_ALL_NAMES = re.compile("|".join("(?:" + p + ")" for _, p, _ in METRICS))


def _first_level(w: str):
    for m in LEVEL_RE.finditer(w):
        num, unit = m.group(1), m.group(2) or ""
        digits = re.sub(r"\D", "", num)
        # 日付・時刻・年のような小さい整数は水準として扱わない
        if "." not in num and "," not in num and len(digits) < 3:
            continue
        return num + unit
    return None


def _lead_date(src: str, pos: int) -> str:
    """「11/20の米国では…Nasdaqは」のように、その数字が指す日付が文頭にあれば拾う。"""
    prefix = src[:pos].rsplit("\n", 1)[-1].rsplit("。", 1)[-1]
    ds = re.findall(r"(\d{1,2}/\d{1,2})(?:[(（][^)）]{1,2}[)）])?の", prefix)
    return ds[-1] if ds else ""


def extract_stats(r: dict) -> list[dict]:
    parts = conclusion_parts(r)
    sources = [
        (r.get("conclusion_full") or r.get("conclusion") or ""),
        r.get("markdown") or "",
    ]
    text_all = "\n".join(sources)
    stats = []
    for label, pat, kind in METRICS:
        name_re = re.compile(pat)
        found = None
        for src in sources:
            for m in name_re.finditer(src):
                w = _window(src, m.end(), _ALL_NAMES)
                if not w.strip() or BAD_CTX.search(w):
                    continue
                if kind != "fut" and re.search(r"先物", w):
                    continue
                st = _build_stat(label, kind, w)
                if st:
                    st['_w'] = w
                    if not st.get("tag") or st["tag"] == "週間":
                        d = _lead_date(src, m.start())
                        if d:
                            st["tag"] = d
                    found = st
                    break
            if found:
                break
        if found:
            # 念のため: 表示する数字が本文にそのまま存在することを確認する
            found.pop('_w', None) if not DEBUG else None
            ok = all((v in text_all or v.replace("-", "−") in text_all or v.replace("-", "－") in text_all or v.replace("-", "▲") in text_all)
                     for v in found.pop("_check", []))
            if ok:
                stats.append(found)
    return stats


def _build_stat(label: str, kind: str, w: str):
    pct = PCT_RE.search(w)
    chg = CHG_RE.search(w)
    level = _first_level(w)
    weekly = "週間" in w
    tag = "週間" if weekly else ""
    if kind == "idx":
        if pct:
            sign, num = pct.group(1), pct.group(2)
            val = _norm_sign(sign) + num + "%"
            return {"label": label, "value": val, "dir": "dn" if _norm_sign(sign) == "-" else "up",
                    "sub": level or "", "tag": tag, "_check": [num + "%"] if False else [num]}
        if chg and level:
            sign, num, unit = chg.group(1), chg.group(2), chg.group(3) or ""
            cv = _norm_sign(sign) + num + unit
            return {"label": label, "value": level, "dir": "dn" if _norm_sign(sign) == "-" else "up",
                    "sub": cv, "tag": tag, "_check": [num, level.rstrip("円ドル")]}
        return None
    if kind == "fx":
        if level and "円" in level and "." in level:
            return {"label": label, "value": level, "dir": "fx", "sub": "", "tag": tag,
                    "_check": [level.rstrip("円")]}
        return None
    if kind == "fut":
        if level and "円" in level:
            d = re.search(r"より(" + NUM + r")円(安|高)い", w)
            sub, dr = "", "flat"
            if d:
                neg = d.group(2) == "安"
                sub = "終値より" + ("-" if neg else "+") + d.group(1) + "円"
                dr = "dn" if neg else "up"
            return {"label": label, "value": level, "dir": dr, "sub": sub, "tag": tag,
                    "_check": [level.rstrip("円")]}
        return None
    if kind == "yld":
        m = re.search(r"(" + NUM + r")\s*%", w)
        if m:
            return {"label": label, "value": m.group(1) + "%", "dir": "flat", "sub": "", "tag": tag,
                    "_check": [m.group(1)]}
        return None
    if kind == "lvl":
        if level:
            sub = ""
            dr = "flat"
            if pct:
                sub = _norm_sign(pct.group(1)) + pct.group(2) + "%"
                dr = "dn" if _norm_sign(pct.group(1)) == "-" else "up"
            return {"label": label, "value": level, "dir": dr, "sub": sub, "tag": tag,
                    "_check": [level.rstrip("円ドル")]}
        return None
    return None


def summarize(r: dict) -> dict:
    s = conclusion_parts(r)
    s["stats"] = extract_stats(r)
    return s
