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

    upper_group_cd が空/None はルート。存在しないコードを指す場合(orphan)は
    ルート扱い(is_orphan=True)。循環参照は構成ノードそれぞれをルート扱い
    (is_orphan=True)にして無限ループを防ぐ。循環に属さない配下ノードは
    通常通りネストされる。
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

    # 循環参照ノードを特定（upper をたどって自分自身に戻るノード）
    cycle_cds = set()
    for g in groups:
        seen = set()
        cur = g
        while cur is not None and cur.group_cd not in seen:
            seen.add(cur.group_cd)
            cur = by_cd.get(cur.upper_group_cd or '')
        if cur is not None and cur.group_cd == g.group_cd:
            cycle_cds.add(g.group_cd)

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
            if c.group_cd in cycle_cds:
                continue  # 循環ノードは自分自身のルート行として別途出力する
            walk(c, depth + 1)

    for g in sorted(roots, key=lambda x: x.group_cd):
        walk(g, 0)
    for g in sorted(orphans, key=lambda x: x.group_cd):
        walk(g, 0, is_orphan=True)
    # 循環参照ノードはそれぞれルート扱いで出力し、循環外の配下は通常通りたどる
    for g in sorted(groups, key=lambda x: x.group_cd):
        if g.group_cd not in visited and g.group_cd in cycle_cds:
            walk(g, 0, is_orphan=True)
    return nodes


@login_required
def group_manager_list(request):
    """部署マスタ: 階層ツリー一覧（GSessionグループマネージャー相当）"""
    groups = list(M_Group.objects.all())
    nodes = build_group_tree(groups)

    # 所属ユーザーを部署ごとにまとめてページ表示時に一括埋め込み（AJAXなし）
    members_map = {}
    belongs = (M_BelongTo.objects
               .select_related('man_number')
               .order_by('man_number__man_number'))
    for b in belongs:
        members_map.setdefault(b.group_cd_id, []).append(b.man_number)
    for node in nodes:
        node['members'] = members_map.get(node['group'].group_cd, [])

    return render(request, 'expenses/group_manager_list.html', {
        'nodes': nodes,
        'total_count': len(groups),
    })
