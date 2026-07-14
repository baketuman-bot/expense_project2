"""
gs2db.h2.db (旧グループウェア GSESSION) を org.h2.tools.Recover で
フォレンジック復元した際に生成されるSQLダンプ (*.h2.sql) をパースするための
純粋関数群。Java/H2への依存はなく、単体テスト可能。

用語:
- 物理テーブルは `O_<内部ID>` という無名テーブル・`C0,C1,...` という無名カラムで
  格納されている。実テーブル名・カラム名は `O_0` という内部メタテーブルに
  CREATE TABLE DDL文字列として保存されている（parse_o0_metadataで復元）。
"""
import re
from datetime import datetime


def stringdecode(s):
    """H2のSTRINGDECODE()関数と同じエスケープ規則で文字列をデコードする"""
    out = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == '\\' and i + 1 < n:
            nc = s[i + 1]
            simple = {'n': '\n', 'r': '\r', 't': '\t', '\\': '\\', '"': '"', "'": "'"}
            if nc in simple:
                out.append(simple[nc])
                i += 2
                continue
            if nc == 'u' and i + 5 < n:
                hexs = s[i + 2:i + 6]
                try:
                    out.append(chr(int(hexs, 16)))
                    i += 6
                    continue
                except ValueError:
                    pass
            out.append(c)
            i += 1
            continue
        out.append(c)
        i += 1
    return ''.join(out)


def sql_unescape_quotes(s):
    """SQL文字列リテラル内の '' (エスケープされた単一引用符) を ' に戻す"""
    return s.replace("''", "'")


def split_top_level(s, sep=','):
    """括弧の深さとシングルクォート文字列を考慮して、トップレベルのsepで分割する"""
    parts = []
    depth = 0
    in_quote = False
    cur = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if in_quote:
            if ch == "'":
                if i + 1 < n and s[i + 1] == "'":
                    cur.append("''")
                    i += 2
                    continue
                in_quote = False
                cur.append(ch)
                i += 1
                continue
            cur.append(ch)
            i += 1
            continue
        if ch == "'":
            in_quote = True
            cur.append(ch)
            i += 1
            continue
        if ch == '(':
            depth += 1
            cur.append(ch)
            i += 1
            continue
        if ch == ')':
            depth -= 1
            cur.append(ch)
            i += 1
            continue
        if ch == sep and depth == 0:
            parts.append(''.join(cur))
            cur = []
            i += 1
            continue
        cur.append(ch)
        i += 1
    if cur or parts:
        parts.append(''.join(cur))
    return [p.strip() for p in parts]


class UnresolvedLob:
    """READ_CLOB_DB()/READ_BLOB_DB() など、テキスト解析だけでは値を復元できない
    ページストア内部LOB参照を表すプレースホルダ。"""

    def __init__(self, raw):
        self.raw = raw

    def __repr__(self):
        return f'UnresolvedLob({self.raw!r})'

    def __eq__(self, other):
        return isinstance(other, UnresolvedLob) and self.raw == other.raw


_STRINGDECODE_RE = re.compile(r"^STRINGDECODE\('(.*)'\)$", re.IGNORECASE | re.DOTALL)
_TIMESTAMP_RE = re.compile(r"^TIMESTAMP\s+'([^']*(?:''[^']*)*)'$", re.IGNORECASE)
_FUNC_CALL_RE = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)\(')


def parse_scalar(token):
    """INSERT ... VALUES(...) の1トークンをPython値に変換する"""
    token = token.strip()
    if token.upper() == 'NULL':
        return None

    m = _STRINGDECODE_RE.match(token)
    if m:
        return stringdecode(sql_unescape_quotes(m.group(1)))

    m = _TIMESTAMP_RE.match(token)
    if m:
        raw = sql_unescape_quotes(m.group(1))
        for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
        raise ValueError(f'パースできないTIMESTAMPです: {raw!r}')

    if token.startswith("'") and token.endswith("'") and len(token) >= 2:
        return sql_unescape_quotes(token[1:-1])

    if _FUNC_CALL_RE.match(token):
        return UnresolvedLob(token)

    return int(token)


def parse_values_tuple(values_str):
    """`INSERT INTO ... VALUES(<values_str>)` の中身をPythonのリストに変換する"""
    return [parse_scalar(tok) for tok in split_top_level(values_str)]
