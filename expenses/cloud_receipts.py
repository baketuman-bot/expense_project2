import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from django.conf import settings

# GCS 設定のデフォルト値（settings.py で上書き可能）
_GCS_BUCKET_DEFAULT = 'cloudruntest_001'
_GCS_FOLDER_DEFAULT = 'image-up-app'
_GCS_PROJECT_DEFAULT = 'cloudruntest-488515'
# gcloud ADC 認証情報のパス（Linux ファイルシステム内にコピー済み）
_GCS_ADC_PATH = '/home/idc_user/expense_project2/gcloud_adc.json'


_SEQ_RE = re.compile(r"^\d{1,6}$")


def parse_cloud_receipt_tokens(raw: str | None) -> list[str]:
    if not raw:
        return []
    tokens: list[str] = []
    for part in re.split(r"[\s,;]+", raw.strip()):
        if not part:
            continue
        tokens.append(part)
    # 重複排除（順序維持）
    dedup: list[str] = []
    seen = set()
    for t in tokens:
        if t in seen:
            continue
        seen.add(t)
        dedup.append(t)
    return dedup


def normalize_seq(token: str) -> str | None:
    t = token.strip()
    if not t:
        return None
    if _SEQ_RE.match(t):
        return f"{int(t):06d}"
    # 000123 のような6桁はそのまま
    if re.match(r"^\d{6}$", t):
        return t
    return None


@dataclass(frozen=True)
class CloudReceiptFile:
    filename: str
    content_type: str
    data: bytes


class CloudReceiptFetchError(RuntimeError):
    pass


def _get_base_url() -> str:
    base = getattr(settings, 'IMAGE_UP_APP_BASE_URL', '')
    base = (base or '').strip().rstrip('/')
    return base


_gcs_client_cache = None


def _get_gcs_client():
    """GCS クライアントを返す（プロセス内でキャッシュ）。"""
    global _gcs_client_cache
    if _gcs_client_cache is not None:
        return _gcs_client_cache

    from google.cloud import storage as gcs_storage
    if not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS') and Path(_GCS_ADC_PATH).exists():
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = _GCS_ADC_PATH

    project = getattr(settings, 'GCS_PROJECT_ID', _GCS_PROJECT_DEFAULT)
    _gcs_client_cache = gcs_storage.Client(project=project)
    return _gcs_client_cache


def _gcs_bucket() -> str:
    return getattr(settings, 'GCS_BUCKET_NAME', _GCS_BUCKET_DEFAULT)


def _gcs_folder() -> str:
    return getattr(settings, 'GCS_FOLDER', _GCS_FOLDER_DEFAULT).rstrip('/')


def fetch_receipt_by_seq(seq: str) -> CloudReceiptFile:
    """Flask(Cloud Run) から指定連番の領収書を取得する。

    Flask側に /api/receipt/<seq> が実装されている前提。
    """
    base = _get_base_url()
    if not base:
        raise CloudReceiptFetchError('IMAGE_UP_APP_BASE_URL が未設定のため、Cloud領収書を取得できません。')

    url = f"{base}/api/receipt/{urllib.parse.quote(seq)}"
    timeout = int(getattr(settings, 'IMAGE_UP_APP_TIMEOUT', 15))

    req = urllib.request.Request(url, headers={'User-Agent': 'expense_project2/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            content_type = resp.headers.get('Content-Type', 'application/octet-stream')
            # Content-Disposition からファイル名抽出（なければ seq で代替）
            cd = resp.headers.get('Content-Disposition', '')
            filename = None
            if cd:
                m = re.search(r'filename="?([^";]+)"?', cd)
                if m:
                    filename = m.group(1)
            if not filename:
                filename = f"{seq}"
            return CloudReceiptFile(filename=filename, content_type=content_type, data=data)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise CloudReceiptFetchError(f'Cloud領収書が見つかりませんでした（{seq}）。') from e
        raise CloudReceiptFetchError(f'Cloud領収書の取得に失敗しました（{seq}）: HTTP {e.code}') from e
    except Exception as e:
        raise CloudReceiptFetchError(f'Cloud領収書の取得に失敗しました（{seq}）: {e}') from e


def check_uploads_by_id(upload_id: str) -> list[dict]:
    """GCS から upload_id に紐づくファイル一覧を取得して辞書リストで返す。"""
    try:
        client = _get_gcs_client()
        prefix = f"{_gcs_folder()}/{upload_id}_"
        blobs = [
            b for b in client.list_blobs(_gcs_bucket(), prefix=prefix)
            if not b.name.endswith('/')
        ]
        return [
            {
                'name': b.name,
                'filename': Path(b.name).name,
                'content_type': b.content_type or 'application/octet-stream',
                'size': b.size,
            }
            for b in blobs
        ]
    except Exception as e:
        raise CloudReceiptFetchError(f'ファイル一覧取得に失敗しました: {e}') from e


def fetch_receipts_by_upload_id(upload_id: str) -> list[CloudReceiptFile]:
    """GCS から upload_id に紐づく全ファイルをダウンロードして返す。"""
    try:
        client = _get_gcs_client()
        prefix = f"{_gcs_folder()}/{upload_id}_"
        blobs = [
            b for b in client.list_blobs(_gcs_bucket(), prefix=prefix)
            if not b.name.endswith('/')
        ]
    except Exception as e:
        raise CloudReceiptFetchError(f'ファイル一覧取得に失敗しました: {e}') from e

    results: list[CloudReceiptFile] = []
    for blob in blobs:
        try:
            data = blob.download_as_bytes()
            filename = Path(blob.name).name
            content_type = blob.content_type or 'application/octet-stream'
            results.append(CloudReceiptFile(
                filename=filename,
                content_type=content_type,
                data=data,
            ))
        except Exception as e:
            raise CloudReceiptFetchError(
                f'ファイルのダウンロードに失敗しました（{blob.name}）: {e}'
            ) from e
    return results
