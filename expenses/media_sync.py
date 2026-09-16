"""申請画像(media)を経理ファイルサーバー共有へミラーするヘルパー。

WSLからのCIFS直接マウントはSMB通信がブロックされ利用できないため、
WindowsのrobocopyをWSLのinterop経由(cmd.exe)で呼び出すことで、
Djangoからの保存直後にWindows側のネイティブSMB経路でコピーする。
アプリ本体の保存(MEDIA_ROOT配下のローカル保存)は従来通りで、
共有への反映はあくまでベストエフォートの副次的な処理として扱う。
"""
import logging
import subprocess
from pathlib import PurePosixPath

logger = logging.getLogger(__name__)

_WINDOWS_CMD = "/mnt/c/Windows/System32/cmd.exe"
_SHARE_MEDIA_ROOT = r"\\172.16.100.15\keirifile\DATA\expense_project2\media"

# MEDIA_ROOT の Windows 側 UNC パス。初回解決後にキャッシュする。
_wsl_media_unc_root: str | None = None


def _resolve_wsl_media_unc_root() -> str | None:
    r"""MEDIA_ROOT を Windows から見た UNC パスに変換して返す。

    `\\wsl.localhost\<ディストロ名>\...` のディストロ名は環境ごとに異なる
    (開発環境は Ubuntu-24.04、本番PCは Ubuntu) ため、ハードコードせず wslpath に
    解決させる。環境変数 WSL_DISTRO_NAME は systemd 配下のプロセスには渡らないので
    ここでは使えない。

    解決できなかった場合は None を返し、呼び出し側は同期をスキップする
    (ベストエフォート処理なので、申請保存そのものは成功させる)。
    """
    global _wsl_media_unc_root
    if _wsl_media_unc_root is not None:
        return _wsl_media_unc_root

    from django.conf import settings

    try:
        completed = subprocess.run(
            ["wslpath", "-w", str(settings.MEDIA_ROOT)],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        logger.exception("MEDIA_ROOTのUNCパス解決に失敗しました。media同期をスキップします")
        return None

    resolved = completed.stdout.strip()
    if not resolved:
        logger.error("wslpathがMEDIA_ROOTのUNCパスを返しませんでした。media同期をスキップします")
        return None

    # 一時的な失敗をキャッシュしないよう、成功時のみ保持する
    _wsl_media_unc_root = resolved
    return resolved


def sync_file_to_share(relative_path: str) -> None:
    """MEDIA_ROOT配下の1ファイルを経理ファイルサーバー共有へ非同期でコピーする。

    ベストエフォート処理。起動に失敗してもログに残すのみで例外は投げない
    （申請保存そのものを失敗させないため）。
    """
    if not relative_path:
        return
    media_unc_root = _resolve_wsl_media_unc_root()
    if media_unc_root is None:
        return
    rel = PurePosixPath(relative_path)
    rel_dir = str(rel.parent).replace('/', '\\')
    filename = rel.name
    if rel_dir == '.':
        src_dir = media_unc_root
        dst_dir = _SHARE_MEDIA_ROOT
    else:
        src_dir = f"{media_unc_root}\\{rel_dir}"
        dst_dir = f"{_SHARE_MEDIA_ROOT}\\{rel_dir}"

    try:
        subprocess.Popen(
            [_WINDOWS_CMD, "/c", "robocopy", src_dir, dst_dir, filename, "/Z", "/R:2", "/W:2"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        logger.exception("経理ファイルサーバーへのmedia同期起動に失敗しました: %s", relative_path)
