"""
Cloud Storage からファイルをダウンロードし、ローカルに保存後、GCS から削除するスクリプト。

対象バケット : cloudruntest_001
対象フォルダ : image-up-app
保存先       : C:/Users/keihaya/Desktop/image_up_app/file
"""

import os
from pathlib import Path
from google.cloud import storage

BUCKET_NAME = "cloudruntest_001"
GCS_FOLDER = "image-up-app"
PROJECT_ID = "cloudruntest-488515"
LOCAL_DEST = Path("/mnt/c/Users/idc_user/Desktop/tmp")

# Windows の gcloud ADC 認証情報を WSL から使う
_ADC_PATH = "/mnt/c/Users/idc_user/AppData/Roaming/gcloud/application_default_credentials.json"
if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") and Path(_ADC_PATH).exists():
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _ADC_PATH


def list_blobs(client: storage.Client) -> list[storage.Blob]:
    """GCS フォルダ内のファイル一覧を返す（フォルダ自体は除外）。"""
    prefix = GCS_FOLDER.rstrip("/") + "/"
    blobs = [
        b for b in client.list_blobs(BUCKET_NAME, prefix=prefix)
        if not b.name.endswith("/")  # フォルダエントリを除外
    ]
    return blobs


def prompt_selection(blobs: list[storage.Blob]) -> list[storage.Blob]:
    """ファイル一覧を表示し、ユーザーにコピーするファイルを選択させる。"""
    print("\n===== Cloud Storage ファイル一覧 =====")
    for i, blob in enumerate(blobs, start=1):
        size_kb = blob.size / 1024 if blob.size else 0
        name = blob.name.removeprefix(GCS_FOLDER.rstrip("/") + "/")
        print(f"  [{i:>3}] {name}  ({size_kb:.1f} KB)")
    print("=====================================")
    print("コピーするファイルの番号を入力してください。")
    print("  例: 1 3 5   → 複数指定はスペース区切り")
    print("  例: all     → すべてのファイルを選択")
    print("  例: q       → キャンセルして終了")

    while True:
        raw = input("\n番号を入力 > ").strip()
        if raw.lower() == "q":
            return []
        if raw.lower() == "all":
            return blobs

        parts = raw.split()
        selected: list[storage.Blob] = []
        valid = True
        for part in parts:
            if not part.isdigit():
                print(f"  ! '{part}' は無効な入力です。半角数字で入力してください。")
                valid = False
                break
            idx = int(part)
            if idx < 1 or idx > len(blobs):
                print(f"  ! {idx} は範囲外です（1〜{len(blobs)}）。")
                valid = False
                break
            selected.append(blobs[idx - 1])

        if valid and selected:
            return selected


def download_and_delete(client: storage.Client, blobs: list[storage.Blob]) -> None:
    """選択されたファイルをダウンロードし、GCS から削除する。"""
    LOCAL_DEST.mkdir(parents=True, exist_ok=True)
    bucket = client.bucket(BUCKET_NAME)

    print()
    for blob in blobs:
        filename = Path(blob.name).name
        dest_path = LOCAL_DEST / filename

        # 同名ファイルが存在する場合は確認
        if dest_path.exists():
            ans = input(f"  '{filename}' はすでに存在します。上書きしますか？ [y/N] > ").strip().lower()
            if ans != "y":
                print(f"  スキップ: {filename}")
                continue

        print(f"  ダウンロード中: {blob.name} → {dest_path}")
        blob.download_to_filename(str(dest_path))

        print(f"  GCS から削除中: {blob.name}")
        bucket.blob(blob.name).delete()

        print(f"  完了: {filename}")

    print("\nすべての処理が完了しました。")


def main() -> None:
    client = storage.Client(project=PROJECT_ID)

    blobs = list_blobs(client)
    if not blobs:
        print(f"gs://{BUCKET_NAME}/{GCS_FOLDER}/ にファイルが見つかりませんでした。")
        return

    selected = prompt_selection(blobs)
    if not selected:
        print("キャンセルしました。")
        return

    print(f"\n選択されたファイル数: {len(selected)}")
    for b in selected:
        print(f"  - {b.name.removeprefix(GCS_FOLDER.rstrip('/') + '/')}")

    confirm = input("\n上記ファイルをダウンロードして GCS から削除します。よろしいですか？ [y/N] > ").strip().lower()
    if confirm != "y":
        print("キャンセルしました。")
        return

    download_and_delete(client, selected)


if __name__ == "__main__":
    main()
