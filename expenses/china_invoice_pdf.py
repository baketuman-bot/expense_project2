"""中国輸出Invoice管理: Invoice PDFからのInvoice No / Total 自動読取。

テキストレイヤーを持つPDFのみ対応する（OCRは行わない）。画像スキャンPDF等で
テキストが取得できない場合はNoneを返し、報告者の手入力に委ねる。

**なぜ座標を使うのか**

実務のInvoiceはラベルと値が別セルに並ぶ表組みで、PDFのテキスト読み順ではこうなる:

    INV_No / DATE / Shipped Per / From / To ...   ← ラベルが全部並び
    IS6A028 / 26/07/08 / AIRCRAFT / ...           ← その後に値が全部並ぶ

つまり `INV_No` の直後にあるのは値ではなく次のラベル（DATE）である。読み順だけを
見る正規表現はここで隣のラベル文字列を値として拾ってしまう。同様に `Total` の
直後にも小計や個数が挟まりうる。

そこで語の座標を使い、ラベルと同じ「行」（y座標が近い語の集まり）の右側から値を
取る。上の例では `INV_No`(x=482) と `IS6A028`(x=542) は同じy座標にあり、素直に
対応が取れる。金額は行内で最も右にあるものを採る（Invoiceの金額欄は右端にあり、
`Total : 1 pkg 394.58` のように個数が先に来ても正しく 394.58 を拾える）。

ラベルと値が同一行に素直に並ぶ単純なPDF向けに、行ベースの正規表現も後段の
フォールバックとして残してある。
"""
import re
from decimal import Decimal, InvalidOperation

import fitz

# 同じ行とみなすy座標の許容差(pt)。実測ではラベルと値のy0差は0.1pt程度だが、
# ラベルと値でフォントサイズが違う場合にベースラインがずれるため余裕を持たせる。
_ROW_TOLERANCE = 4.0

# --- ラベルの語 ---------------------------------------------------------
# 'INV_No' 'Invoice#' 'INVOICE NO.' のように、1語でNo部分まで含む表記
_INV_LABEL_WITH_NO = re.compile(r'^(?:inv|invoice)[\s_\-.]*(?:no\.?|number|#)[:：]?$', re.I)
# 'Invoice' 'INV' のようにNo部分が次の語に分かれる表記
_INV_LABEL_HEAD = re.compile(r'^(?:inv|invoice)[.:：]?$', re.I)
_INV_LABEL_TAIL = re.compile(r'^(?:no\.?|number|#)[:：]?$', re.I)

_TOTAL_LABEL = re.compile(r'^(?:grand[\s_-]*)?total[:：]?$', re.I)
_SUBTOTAL_LABEL = re.compile(r'^sub[\s_-]*total[:：]?$', re.I)
_SUB_PREFIX = re.compile(r'^sub$', re.I)

# --- 値の語 -------------------------------------------------------------
_INVOICE_NO_VALUE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9\-/_]*$')
# 金額は「小数なし」か「小数2桁」のみ受け付ける。実物のInvoiceは同じ行に
# 正味重量(0.010)や体積(0.018)といった小数3桁以上の数値が並ぶことがあり、
# それらを金額と誤認しないための絞り込みでもある。
_AMOUNT_VALUE = re.compile(r'^[0-9][0-9,]*(?:\.\d{2})?$')
# 値として拾ってはいけない区切り記号・通貨記号
_IGNORABLE_VALUE = re.compile(r'^(?:[:：\-–—]|US\$|USD|\$|¥|JPY|CNY|RMB)$', re.I)

# --- フォールバック（ラベルと値が同一行に素直に並ぶ単純なPDF向け）-------
# 行をまたがないよう、空白は改行を含まない [ \t] に限定する。'Invoice No.' の
# 次の行にある別ラベルを値として拾う事故を防ぐため。
_FALLBACK_INVOICE_NO = re.compile(
    r'(?:inv|invoice)[ \t_\-.]*(?:no\.?|number|#)[ \t]*[:：·]?[ \t]*'
    r'([A-Za-z0-9][A-Za-z0-9\-/_]*)', re.I)
# 'Subtotal' / 'Sub Total' を合計と誤認しないよう除外する。
_FALLBACK_TOTAL = re.compile(
    r'(?<!sub)(?<!sub )total[ \t]*[:：]?[ \t]*(?:US\$|USD|\$|¥)?[ \t]*'
    r'([0-9][0-9,]*(?:\.\d{2})?)', re.I)


def _to_decimal(token):
    try:
        return Decimal(token.replace(',', ''))
    except InvalidOperation:
        return None


def _rows(page):
    """ページ内の語をy座標で行にまとめ、[(y, [語, ...])] を返す。

    各行の語はx昇順。行はy昇順。語は PyMuPDF の
    (x0, y0, x1, y1, text, block_no, line_no, word_no) タプル。
    """
    rows = []
    for word in sorted(page.get_text("words"), key=lambda w: (w[1], w[0])):
        for row in rows:
            if abs(row[0] - word[1]) <= _ROW_TOLERANCE:
                row[1].append(word)
                break
        else:
            rows.append((word[1], [word]))
    return [(y, sorted(words, key=lambda w: w[0])) for y, words in rows]


def _invoice_label_end(words, i):
    """words[i] から始まる語がInvoice Noラベルなら、その最後の語のindexを返す。

    ラベルでなければ None。'INV_No' は1語、'Invoice No.' は2語で構成される。
    """
    if _INV_LABEL_WITH_NO.match(words[i][4]):
        return i
    if _INV_LABEL_HEAD.match(words[i][4]):
        if i + 1 < len(words) and _INV_LABEL_TAIL.match(words[i + 1][4]):
            return i + 1
    return None


def _find_invoice_no(rows):
    """ラベルと同じ行の右側から、最初に現れるInvoice Noらしき語を返す。"""
    for _y, words in rows:
        for i in range(len(words)):
            end = _invoice_label_end(words, i)
            if end is None:
                continue
            for candidate in words[end + 1:]:
                token = candidate[4].strip()
                if not token or _IGNORABLE_VALUE.match(token):
                    continue
                # 右隣が別のラベルだった場合（値が空欄）は、そのラベルを
                # 値として拾わないようここで打ち切る
                if _invoice_label_end([candidate], 0) is not None:
                    break
                if _INVOICE_NO_VALUE.match(token):
                    return token
                break
            break
    return None


def _find_total(rows):
    """Totalラベルと同じ行で、最も右にある金額を返す。

    Invoiceの金額欄は右端にあり、'Total : 1 pkg 394.58' のように個数などが
    先に来ても、最右の数値を採れば金額になる。
    """
    for _y, words in rows:
        for i, word in enumerate(words):
            token = word[4]
            if _SUBTOTAL_LABEL.match(token):
                break  # この行は小計。合計として扱わない
            if not _TOTAL_LABEL.match(token):
                continue
            if i > 0 and _SUB_PREFIX.match(words[i - 1][4]):
                break  # 'Sub' 'Total' と2語に分かれた小計
            amounts = [
                w[4] for w in words[i + 1:] if _AMOUNT_VALUE.match(w[4].strip())
            ]
            if amounts:
                value = _to_decimal(amounts[-1])
                if value is not None:
                    return value
            break
    return None


def _extract_by_layout(doc):
    """座標ベースの抽出。ページ順に走査し、先に見つかったものを採る。"""
    invoice_no = None
    invoice_total = None
    for page in doc:
        rows = _rows(page)
        if invoice_no is None:
            invoice_no = _find_invoice_no(rows)
        if invoice_total is None:
            invoice_total = _find_total(rows)
        if invoice_no is not None and invoice_total is not None:
            break
    return invoice_no, invoice_total


def _extract_by_text(doc):
    """フォールバック。ラベルと値が同一行に素直に並ぶPDF向け。"""
    text = ''
    for page in doc:
        text += page.get_text()

    invoice_no = None
    match = _FALLBACK_INVOICE_NO.search(text)
    if match:
        invoice_no = match.group(1).strip()

    invoice_total = None
    match = _FALLBACK_TOTAL.search(text)
    if match:
        invoice_total = _to_decimal(match.group(1))

    return invoice_no, invoice_total


def extract_invoice_fields(pdf_bytes):
    """PDFからInvoice NoとTotalを読み取る。

    戻り値: {'invoice_no': str | None, 'invoice_total': Decimal | None}
    読み取れなかった項目はNoneになる（呼び出し側で手入力に委ねる）。
    PDFとして壊れている場合も例外を送出せず、両方Noneを返す。
    """
    result = {'invoice_no': None, 'invoice_total': None}

    try:
        doc = fitz.open(stream=pdf_bytes, filetype='pdf')
    except Exception:
        return result

    try:
        invoice_no, invoice_total = _extract_by_layout(doc)
        if invoice_no is None or invoice_total is None:
            fallback_no, fallback_total = _extract_by_text(doc)
            invoice_no = invoice_no or fallback_no
            invoice_total = invoice_total if invoice_total is not None else fallback_total
    except Exception:
        # 読取はベストエフォート。どんなPDFでも申請自体は続行できるようにする
        return result
    finally:
        doc.close()

    result['invoice_no'] = invoice_no
    result['invoice_total'] = invoice_total
    return result
