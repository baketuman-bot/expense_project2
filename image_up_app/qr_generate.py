import argparse
from pathlib import Path

import qrcode


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload URL を埋め込んだQRコードを生成します。")
    parser.add_argument("url", help="アップロードページのURL")
    parser.add_argument("--out", default="upload_qr.png", help="出力ファイル名")
    args = parser.parse_args()

    img = qrcode.make(args.url)
    output = Path(args.out)
    img.save(output)
    print(f"QRコードを作成しました: {output}")


if __name__ == "__main__":
    main()
