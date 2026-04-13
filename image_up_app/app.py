import logging
import os
from typing import Optional, Tuple
from datetime import timedelta, datetime

from flask import Flask, jsonify, make_response, render_template, request
from google.cloud import storage
from werkzeug.utils import secure_filename

app = Flask(__name__)

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("upload-app")

# 環境変数
BUCKET_NAME = os.getenv("GCS_BUCKET", "cloudruntest_001")
UPLOAD_FOLDER = os.getenv("GCS_FOLDER", "image-up-app")
COUNTER_BLOB = os.getenv("GCS_COUNTER_BLOB", "image-up-app/.counter")

# GCS クライアントをアプリ起動時に1回だけ初期化
_storage_client = storage.Client()


class SequenceError(Exception):
    """連番取得の失敗を表す例外。"""



def get_storage_client() -> storage.Client:
    return _storage_client



def _read_counter_value(blob: storage.Blob) -> int:
    if not blob.exists():
        return 0

    data = blob.download_as_text().strip()
    if not data:
        return 0

    return int(data)



def get_next_sequence(client: storage.Client, bucket_name: str, counter_blob: str) -> int:
    """
    GCSの世代管理を使って安全に連番を採番する。
    同時アクセス時はリトライして重複を防ぐ。
    """
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(counter_blob)

    for _ in range(20):
        if not blob.exists():
            try:
                # 0 の初期値を作成（未作成時のみ）
                blob.upload_from_string("0", if_generation_match=0)
            except Exception:
                # 同時作成で競合した場合は次のループへ
                continue

        blob.reload()
        current = _read_counter_value(blob)
        new_value = current + 1

        try:
            blob.upload_from_string(str(new_value), if_generation_match=blob.generation)
            return new_value
        except Exception:
            # 世代不一致の場合は再試行
            continue

    raise SequenceError("連番の採番に失敗しました。")



def upload_to_gcs(
    client: storage.Client,
    bucket_name: str,
    folder: str,
    file_storage,
) -> Tuple[str, int]:
    """
    ファイルをGCSにアップロードし、オブジェクト名と採番を返す。
    """
    original_name = secure_filename(file_storage.filename or "")
    if not original_name:
        raise ValueError("ファイル名が取得できません。")

    seq = get_next_sequence(client, bucket_name, COUNTER_BLOB)
    filename = f"{seq:06d}_{original_name}"
    object_name = f"{folder}/{filename}"

    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_name)
    blob.upload_from_file(file_storage.stream, content_type=file_storage.mimetype)

    return object_name, seq


@app.route("/", methods=["GET"])
def index():
    upload_id = request.args.get("id", "").strip()
    return render_template("upload.html", upload_id=upload_id)


@app.route("/upload", methods=["POST"])
def upload():
    upload_id = (request.form.get("upload_id") or "").strip()

    if "photo" not in request.files:
        return render_template("upload.html", upload_id=upload_id, error="ファイルが選択されていません。")

    file_storage = request.files["photo"]
    if file_storage.filename is None or file_storage.filename == "":
        return render_template("upload.html", upload_id=upload_id, error="ファイル名が空です。")

    try:
        client = get_storage_client()
        original_name = secure_filename(file_storage.filename or "")
        if not original_name:
            raise ValueError("ファイル名が取得できません。")

        if upload_id:
            # 新方式: {upload_id}_{yyyymmdd}_{ファイル名左10文字} で保存
            name_part, ext = os.path.splitext(original_name)
            date_str = datetime.now().strftime("%Y%m%d")
            short_name = name_part[:10]
            filename = f"{upload_id}_{date_str}_{short_name}{ext}"
        else:
            # フォールバック: 旧来の連番方式
            seq = get_next_sequence(client, BUCKET_NAME, COUNTER_BLOB)
            filename = f"{seq:06d}_{original_name}"

        object_name = f"{UPLOAD_FOLDER}/{filename}"
        bucket = client.bucket(BUCKET_NAME)
        blob = bucket.blob(object_name)
        blob.upload_from_file(file_storage.stream, content_type=file_storage.mimetype)
        logger.info("Uploaded to GCS: %s", object_name)
        return render_template(
            "upload.html",
            upload_id=upload_id,
            message=f"アップロード成功: {filename}",
        )
    except Exception as exc:
        logger.exception("Upload failed")
        return render_template("upload.html", upload_id=upload_id, error=f"アップロード失敗: {exc}")


def _find_blob_by_seq(client: storage.Client, bucket_name: str, folder: str, seq: str) -> Optional[storage.Blob]:
    """{folder}/{seq:06d}_ で始まるオブジェクトを検索して最新を返す。"""
    bucket = client.bucket(bucket_name)
    prefix = f"{folder}/{seq}_"
    blobs = list(client.list_blobs(bucket, prefix=prefix, max_results=50))
    if not blobs:
        return None
    blobs.sort(key=lambda b: (b.updated or 0), reverse=True)
    return blobs[0]


@app.get("/api/receipts_by_id/<upload_id>")
def api_receipts_by_id(upload_id: str):
    """アップロードIDで始まるファイル一覧を返す（Django 取り込み用）。"""
    uid = upload_id.strip()
    if not uid:
        return jsonify({"error": "upload_id is required"}), 400
    try:
        client = get_storage_client()
        bucket = client.bucket(BUCKET_NAME)
        prefix = f"{UPLOAD_FOLDER}/{uid}_"
        blobs = list(client.list_blobs(bucket, prefix=prefix, max_results=50))
        items = []
        for b in blobs:
            items.append({
                "name": b.name,
                "filename": os.path.basename(b.name),
                "size": int(getattr(b, "size", 0) or 0),
                "updated": (b.updated.isoformat() if getattr(b, "updated", None) else None),
                "content_type": b.content_type,
            })
        return jsonify({"upload_id": uid, "items": items, "count": len(items)})
    except Exception as exc:
        logger.exception("api_receipts_by_id failed")
        return jsonify({"error": str(exc)}), 500


@app.get("/api/receipt_by_upload/<upload_id>/<path:filename>")
def api_receipt_by_upload(upload_id: str, filename: str):
    """アップロードID + ファイル名でファイル本体を返す（Django 取り込み用）。"""
    try:
        object_name = f"{UPLOAD_FOLDER}/{upload_id}_{filename}"
        client = get_storage_client()
        bucket = client.bucket(BUCKET_NAME)
        blob = bucket.blob(object_name)
        if not blob.exists():
            return jsonify({"error": "not found"}), 404
        data = blob.download_as_bytes()
        resp = make_response(data)
        resp.headers["Content-Type"] = blob.content_type or "application/octet-stream"
        resp.headers["Content-Disposition"] = f'attachment; filename="{os.path.basename(blob.name)}"'
        resp.headers["X-GCS-Object-Name"] = blob.name
        return resp
    except Exception as exc:
        logger.exception("api_receipt_by_upload failed")
        return jsonify({"error": str(exc)}), 500


@app.get("/api/healthz")
def api_healthz():
    return jsonify({"ok": True, "bucket": BUCKET_NAME, "folder": UPLOAD_FOLDER})


@app.get("/api/receipt/<seq>")
def api_receipt(seq: str):
    """連番から領収書の実体を返す（Django取り込み用）。

    - 200: ファイルバイナリ
    - 404: 未存在
    """
    seq_norm = seq.strip()
    if not seq_norm.isdigit():
        return jsonify({"error": "seq must be digits"}), 400
    seq_norm = f"{int(seq_norm):06d}"

    try:
        client = get_storage_client()
        blob = _find_blob_by_seq(client, BUCKET_NAME, UPLOAD_FOLDER, seq_norm)
        if not blob:
            return jsonify({"error": "not found", "seq": seq_norm}), 404

        data = blob.download_as_bytes()
        filename = os.path.basename(blob.name)
        resp = make_response(data)
        resp.headers["Content-Type"] = blob.content_type or "application/octet-stream"
        resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        resp.headers["X-GCS-Object-Name"] = blob.name
        return resp
    except Exception as exc:
        logger.exception("api_receipt failed")
        return jsonify({"error": str(exc)}), 500


@app.get("/api/receipts")
def api_receipts():
    """フォルダ配下の領収書一覧（簡易）。"""
    try:
        limit = int(request.args.get("limit", "50"))
        limit = max(1, min(limit, 200))
        client = get_storage_client()
        bucket = client.bucket(BUCKET_NAME)
        blobs = list(client.list_blobs(bucket, prefix=f"{UPLOAD_FOLDER}/", max_results=limit))
        items = []
        for b in blobs:
            items.append({
                "name": b.name,
                "size": int(getattr(b, "size", 0) or 0),
                "updated": (b.updated.isoformat() if getattr(b, "updated", None) else None),
                "content_type": b.content_type,
            })
        return jsonify({"items": items})
    except Exception as exc:
        logger.exception("api_receipts failed")
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")), debug=False)
