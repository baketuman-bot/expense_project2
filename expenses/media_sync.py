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
_WSL_MEDIA_UNC_ROOT = r"\\wsl.localhost\Ubuntu-24.04\home\idc_user\expense_project2\media"


def sync_file_to_share(relative_path: str) -> None:
    """MEDIA_ROOT配下の1ファイルを経理ファイルサーバー共有へ非同期でコピーする。

    ベストエフォート処理。起動に失敗してもログに残すのみで例外は投げない
    （申請保存そのものを失敗させないため）。
    """
    if not relative_path:
        return
    rel = PurePosixPath(relative_path)
    rel_dir = str(rel.parent).replace('/', '\\')
    filename = rel.name
    if rel_dir == '.':
        src_dir = _WSL_MEDIA_UNC_ROOT
        dst_dir = _SHARE_MEDIA_ROOT
    else:
        src_dir = f"{_WSL_MEDIA_UNC_ROOT}\\{rel_dir}"
        dst_dir = f"{_SHARE_MEDIA_ROOT}\\{rel_dir}"

    try:
        subprocess.Popen(
            [_WINDOWS_CMD, "/c", "robocopy", src_dir, dst_dir, filename, "/Z", "/R:2", "/W:2"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        logger.exception("経理ファイルサーバーへのmedia同期起動に失敗しました: %s", relative_path)
