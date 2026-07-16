"""グループ/ユーザーマネージャー（m_group / m_user 専用一覧ビュー）

GSessionのグループマネージャー/ユーザマネージャーUIを参考に、
汎用マスタ画面 (settings_master_list) から委譲される専用一覧を提供する。
追加・編集・削除は既存の settings_master_* ビューを再利用する。
"""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from .models import M_BelongTo, M_Bumon, M_Group, M_Post, M_User


def build_group_tree(groups):
    """M_Groupのリストから表示順（DFS・同階層はgroup_cd昇順）のノードリストを作る。

    upper_group_cd が空/None はルート。存在しないコードを指す場合(orphan)と
    循環参照ノードはルート扱い(is_orphan=True)にして無限ループを防ぐ。
    """
    by_cd = {g.group_cd: g for g in groups}
    children = {}
    roots = []
    orphans = []
    for g in groups:
        up = g.upper_group_cd or ''
        if not up:
            roots.append(g)
        elif up in by_cd:
            children.setdefault(up, []).append(g)
        else:
            orphans.append(g)

    nodes = []
    visited = set()

    def walk(g, depth, is_orphan=False):
        if g.group_cd in visited:
            return
        visited.add(g.group_cd)
        nodes.append({
            'group': g, 'depth': depth,
            'indent': depth * 18, 'is_orphan': is_orphan,
        })
        for c in sorted(children.get(g.group_cd, []), key=lambda x: x.group_cd):
            walk(c, depth + 1, is_orphan)

    for g in sorted(roots, key=lambda x: x.group_cd):
        walk(g, 0)
    for g in sorted(orphans, key=lambda x: x.group_cd):
        walk(g, 0, is_orphan=True)
    # 循環参照でどのルートからも到達できなかった残りを回収
    for g in sorted(groups, key=lambda x: x.group_cd):
        if g.group_cd not in visited:
            walk(g, 0, is_orphan=True)
    return nodes
