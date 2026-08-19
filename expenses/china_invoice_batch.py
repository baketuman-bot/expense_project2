"""中国輸出Invoice管理: 報告ウィザードの一時ファイル保管。

ステップ1でドロップされたInvoiceファイルを MEDIA_ROOT 配下の一時ディレクトリに置き、
メタ情報を session に持つ。ステップ2の報告確定時に本保存し、一時ディレクトリを破棄する。
DBには一切書き込まないため、既存のT_ChinaInvoice系の画面・集計に影響しない。
"""
import datetime
import os
import re
import shutil
import uuid

from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.utils.text import get_valid_filename

SESSION_KEY = 'china_invoice_batch'
TMP_SUBDIR = 'china_invoice_tmp'

_BATCH_ID_PATTERN = re.compile(r'^[0-9a-f]{32}$')


def _tmp_root():
    return os.path.join(settings.MEDIA_ROOT, TMP_SUBDIR)


def batch_dir(batch_id):
    """バッチの一時ディレクトリの絶対パス。batch_idはuuid4().hexのみ許容する。"""
    if not _BATCH_ID_PATTERN.match(batch_id or ''):
        raise SuspiciousOperation('不正なバッチIDです。')
    return os.path.join(_tmp_root(), batch_id)


def batch_file_path(batch_id, stored_name):
    """一時ファイルの絶対パス。ディレクトリ区切りを含む名前はパストラバーサルとして拒否する。"""
    if (not stored_name or '/' in stored_name or '\\' in stored_name
            or stored_name in ('.', '..')):
        raise SuspiciousOperation('不正なファイル名です。')
    return os.path.join(batch_dir(batch_id), stored_name)


def _safe_stored_name(index, original_name):
    # get_valid_filename は結果が '' / '.' / '..' になると SuspiciousFileOperation を送出する。
    # 拡張子検証を通ったファイルではまず起きないが、念のためフォールバックする。
    try:
        safe = get_valid_filename(original_name)
    except Exception:
        safe = 'file'
    return f'{index}_{safe}'


def create_batch(request, files, extracted):
    """filesを一時ディレクトリへ保存し、sessionにメタを書いてbatch_idを返す。

    files: UploadedFile のリスト
    extracted: files と同じ長さの dict のリスト。
               各要素は {'invoice_no': str|None, 'invoice_total': Decimal|None}
    """
    discard_batch(request)
    batch_id = uuid.uuid4().hex
    target_dir = batch_dir(batch_id)
    os.makedirs(target_dir, exist_ok=True)

    items = []
    for index, (uploaded, ex) in enumerate(zip(files, extracted)):
        original_name = os.path.basename(uploaded.name)
        stored_name = _safe_stored_name(index, original_name)
        with open(os.path.join(target_dir, stored_name), 'wb') as out:
            for chunk in uploaded.chunks():
                out.write(chunk)
        total = ex.get('invoice_total')
        items.append({
            'index': index,
            'original_name': original_name,
            'stored_name': stored_name,
            'invoice_no': ex.get('invoice_no'),
            # sessionはJSON化されるためDecimalを直接置けない
            'invoice_total': str(total) if total is not None else None,
        })

    request.session[SESSION_KEY] = {
        'batch_id': batch_id,
        'created_at': datetime.datetime.now().isoformat(),
        'items': items,
    }
    request.session.modified = True
    return batch_id


def get_batch(request):
    return request.session.get(SESSION_KEY)


def get_item(batch, index):
    for item in batch['items']:
        if item['index'] == index:
            return item
    return None


def remove_item(request, index):
    """指定indexの一時ファイルを消し、itemsから除く。残り件数を返す。"""
    batch = get_batch(request)
    if not batch:
        return 0
    item = get_item(batch, index)
    if item is None:
        return len(batch['items'])
    path = batch_file_path(batch['batch_id'], item['stored_name'])
    if os.path.exists(path):
        os.remove(path)
    batch['items'] = [i for i in batch['items'] if i['index'] != index]
    request.session[SESSION_KEY] = batch
    request.session.modified = True
    return len(batch['items'])


def discard_batch(request):
    """一時ディレクトリごと削除し、セッションキーを消す。"""
    batch = request.session.pop(SESSION_KEY, None)
    if not batch:
        return
    request.session.modified = True
    try:
        shutil.rmtree(batch_dir(batch['batch_id']), ignore_errors=True)
    except SuspiciousOperation:
        # セッションが壊れている場合。掃除できないだけなので握りつぶす
        pass


def cleanup_stale_batches(max_age_hours=24, dry_run=False):
    """一時ルート配下で更新時刻がmax_age_hoursより古いディレクトリを削除し、件数を返す。"""
    root = _tmp_root()
    if not os.path.isdir(root):
        return 0
    threshold = datetime.datetime.now().timestamp() - max_age_hours * 3600
    removed = 0
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        if os.path.getmtime(path) < threshold:
            if not dry_run:
                shutil.rmtree(path, ignore_errors=True)
            removed += 1
    return removed
