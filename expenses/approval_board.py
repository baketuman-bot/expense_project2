"""申請詳細・承認画面の「決裁状況」「承認欄（印鑑）」「承認ルート」表示用データを組み立てる。

ビューから受け取った workflow_actions / pending_approvers / ステップ定義を、
テンプレート `_approval_board.html` が描画しやすい dict に変換する純粋関数群。
DB アクセスは行わない（呼び出し側で取得済みのオブジェクトだけを見る）。
"""
import re

from django.utils import timezone

from .utils import OR_APPROVAL_SCOPE_LABELS

# 承認待ち段の経過バーを 100% とみなす日数（目安）
ELAPSED_FULL_DAYS = 2.0

_SUBMIT_CODES = {'INPRO', 'SUB'}
_APPROVE_CODES = {'APPROVED', 'FNS'}

# 文書ステータス → 全体状態
_DOC_STATE = {
    'DRAFT': 'draft',
    'INPRO': 'wait',
    'APPROVED': 'wait',
    'RETURNED': 'return',
    'REJECTED': 'reject',
    'FNS': 'done',
    'CANCEL': 'cancel',
}

# アクションコード → 承認ルート上の状態クラス
_ACTION_STATE = {
    'INPRO': 'src',
    'SUB': 'src',
    'APPROVED': 'done',
    'FNS': 'done',
    'RETURNED': 'return',
    'REJECTED': 'reject',
    'CANCEL': 'cancel',
}

_PILL_LABEL = {
    'src': '申請',
    'done': '承認済み',
    'now': '承認待ち',
    'wait': '未着手',
    'return': '差戻し',
    'reject': '却下',
    'cancel': '取り消し',
    'draft': '未提出',
}


def stamp_name(user_name):
    """印影の下段に出す「姓」。半角/全角スペース区切りの先頭、無ければ先頭2文字。"""
    name = (user_name or '').strip()
    if not name:
        return ''
    parts = re.split(r'[\s　]+', name)
    if len(parts) >= 2 and parts[0]:
        return parts[0]
    return name[:2]


def _local(dt):
    return timezone.localtime(dt) if timezone.is_aware(dt) else dt


def stamp_date(dt):
    """印影の中段に出す日付 `YY.M.D`。"""
    dt = _local(dt)
    return f"{dt:%y}.{dt.month}.{dt.day}"


def _date_text(dt):
    dt = _local(dt)
    return f"{dt.month}月{dt.day}日"


def _datetime_text(dt):
    dt = _local(dt)
    return f"{dt.month}月{dt.day}日 {dt:%H:%M}"


def _post_name(user):
    post = getattr(user, 'post_cd', None)
    return (getattr(post, 'post_name', '') or '') if post else ''


def _user_name(user):
    return getattr(user, 'user_name', '') or ''


def _code(action):
    st = getattr(action, 'action_status', None)
    return (getattr(st, 'status_cd', '') or '') if st else ''


def _step_order(action):
    step = getattr(action, 'step', None)
    return getattr(step, 'step_order', None) if step else None


def _elapsed_pct(since, now):
    if since is None:
        return 0
    days = max(0.0, (now - since).total_seconds() / 86400.0)
    return int(min(days / ELAPSED_FULL_DAYS, 1.0) * 100)


def _elapsed_text(since, until):
    secs = max(0.0, (until - since).total_seconds())
    if secs < 3600:
        return f"{int(secs // 60)}分"
    if secs < 86400:
        return f"{secs / 3600:.1f}時間"
    return f"{secs / 86400:.1f}日"


# 印影の上段に出す役職名の言い換え（役職マスタの表記が印影に馴染まないもの）
STAMP_POST_ALIASES = {
    '一般社員': '担当',
}


def stamp_post(post_name):
    """印影の上段に出す役職名。`一般社員` は `担当` に言い換える。"""
    name = (post_name or '').strip()
    return STAMP_POST_ALIASES.get(name, name)


def _make_stamp(user, dt):
    return {'top': stamp_post(_post_name(user)), 'date': stamp_date(dt), 'name': stamp_name(_user_name(user))}


def _step_caption(step):
    """ステップ定義から承認欄ヘッダーの役職キャプションを決める。"""
    scope = str(getattr(step, 'allowed_bumon_scope', '') or '').strip().lower()
    if scope in OR_APPROVAL_SCOPE_LABELS:
        return OR_APPROVAL_SCOPE_LABELS[scope]
    post = getattr(step, 'approver_post', None)
    return (getattr(post, 'post_name', '') or '') if post else ''


def build_approval_board(expense, workflow_actions, pending_approvers, steps, progress=None, now=None):
    """承認欄・決裁状況・承認ルートの表示データを返す。ステップ定義が無ければ None。

    戻り値:
        state: draft / wait / done / return / reject / cancel
        title: 「2段目で承認待ち」等の見出し
        current / total: 承認済み段数 / 総段数
        next_label: 次の承認者（承認待ち時のみ）
        completed_text: 完了日（決裁済み時のみ）
        segments: 段ごとのプログレスバー要素（起案を除く、1段目→最終）
        columns: 承認欄の列（最終段 → 1段目 → 申請者。右が起案になるよう並べ替え済み）
        route: 承認ルート（履歴 + 承認予定者、時系列）
    """
    steps = sorted(list(steps or []), key=lambda s: s.step_order or 0)
    if not steps:
        return None
    # 表示上の段数は step_order の値ではなく並び順（1,2,5 のような飛び番でも 1,2,3 段目と出す）
    pos_by_order = {s.step_order: i + 1 for i, s in enumerate(steps)}
    last_order = steps[-1].step_order

    def _role(so):
        if so is None:
            return ''
        if so == last_order:
            return '決裁'
        return f"{pos_by_order.get(so, so)}段目"

    now = now or timezone.now()
    actions = sorted(list(workflow_actions or []), key=lambda a: a.actioned_at)
    pending = sorted(list(pending_approvers or []), key=lambda p: p.step_order or 0)

    doc_code = getattr(getattr(expense, 'status_cd', None), 'status_cd', '') or ''
    state = _DOC_STATE.get(doc_code, 'wait')

    # 現サイクル = 最後の提出以降。差戻し→再提出で承認は1段目からやり直しになるため、
    # 承認欄には前サイクルの承認・差戻しを反映しない。
    submits = [a for a in actions if _code(a) in _SUBMIT_CODES]
    last_submit = submits[-1] if submits else None
    cycle_start = last_submit.actioned_at if last_submit else None
    cycle_actions = [a for a in actions if cycle_start is None or a.actioned_at >= cycle_start]

    # 段ごとの最新アクション（現サイクル内、ステップ番号のあるもの）
    latest_by_step = {}
    for a in cycle_actions:
        so = _step_order(a)
        if so is not None and _code(a) in (_APPROVE_CODES | {'RETURNED', 'REJECTED'}):
            latest_by_step[so] = a

    pending_orders = [p.step_order for p in pending]
    pending_by_step = {p.step_order: p for p in pending}
    now_order = pending_orders[0] if (state == 'wait' and pending_orders) else None

    # 差戻し・却下が起きた段
    stop_action = None
    if state in ('return', 'reject'):
        wanted = 'RETURNED' if state == 'return' else 'REJECTED'
        for a in reversed(cycle_actions):
            if _code(a) == wanted:
                stop_action = a
                break
    stop_order = _step_order(stop_action) if stop_action else None

    # 経過バーの起点 = 現サイクル内で最後に何かが起きた時刻
    last_event_at = cycle_actions[-1].actioned_at if cycle_actions else None

    # ── 段ごとの状態を決める ──
    step_states = {}
    for s in steps:
        so = s.step_order
        act = latest_by_step.get(so)
        if stop_order is not None and so == stop_order and stop_action is not None:
            st = state  # 'return' / 'reject'
        elif so == now_order:
            st = 'now'
        elif act is not None and _code(act) in _APPROVE_CODES and (stop_order is None or so < stop_order):
            st = 'done'
        else:
            st = 'wait'
        step_states[so] = st

    done_count = sum(1 for st in step_states.values() if st == 'done')
    total = len(steps)
    current = done_count
    if progress and progress.get('total'):
        total = progress['total']
        current = max(0, min(progress.get('current', done_count), total))
        if state in ('return', 'reject', 'wait'):
            # 表示は承認欄と矛盾させない（自動承認等で差が出た場合は承認欄側を優先）
            current = done_count

    # ── 見出し ──
    next_label = None
    completed_text = None
    if state == 'draft':
        title = '下書き'
    elif state == 'done':
        title = '決裁済み'
        fns = [a for a in cycle_actions if _code(a) in _APPROVE_CODES]
        if fns:
            completed_text = f"{_date_text(fns[-1].actioned_at)} 完了"
    elif state == 'return':
        title = f"{pos_by_order.get(stop_order, stop_order)}段目で差戻し" if stop_order else '差戻し'
    elif state == 'reject':
        title = f"{pos_by_order.get(stop_order, stop_order)}段目で却下" if stop_order else '却下'
    elif state == 'cancel':
        title = '取り消し済み'
    else:
        if now_order is not None:
            title = f"{pos_by_order.get(now_order, now_order)}段目で承認待ち"
            p = pending_by_step[now_order]
            post = _post_name(p.man_number)
            next_label = _user_name(p.man_number) + (f"（{post}）" if post else '')
        else:
            title = '承認待ち'

    # ── セグメントバー ──
    segments = []
    for s in steps:
        st = step_states[s.step_order]
        seg = {'state': st, 'label': _step_caption(s), 'pct': 0}
        if st == 'now':
            seg['pct'] = _elapsed_pct(last_event_at, now)
        segments.append(seg)

    # ── 承認欄の列（最終段→1段目→申請者） ──
    columns = []
    for idx, s in enumerate(reversed(steps)):
        so = s.step_order
        st = step_states[so]
        act = latest_by_step.get(so)
        pend = pending_by_step.get(so)
        col = {
            'role': _role(so),
            'cap': _step_caption(s),
            'state': st,
            'user_name': '',
            'date_text': '',
            'stamp': None,
            'pct': 0,
        }
        if st in ('done', 'return', 'reject') and act is not None:
            user = act.approver_man_number
            col['user_name'] = _user_name(user)
            col['cap'] = _post_name(user) or col['cap']
            col['date_text'] = _date_text(act.actioned_at)
            col['stamp'] = _make_stamp(user, act.actioned_at)
        elif pend is not None:
            col['user_name'] = _user_name(pend.man_number)
            col['cap'] = _post_name(pend.man_number) or col['cap']
            if st == 'now':
                col['pct'] = _elapsed_pct(last_event_at, now)
        columns.append(col)

    applicant = getattr(expense, 'man_number', None)
    app_col = {
        'role': '申請者',
        'cap': '起案',
        'state': 'draft',
        'user_name': _user_name(applicant),
        'date_text': '',
        'stamp': None,
        'pct': 0,
    }
    if state == 'cancel':
        cancels = [a for a in actions if _code(a) == 'CANCEL']
        at = cancels[-1].actioned_at if cancels else (last_submit.actioned_at if last_submit else expense.created_at)
        app_col.update(state='cancel', date_text=_date_text(at), stamp=_make_stamp(applicant, at))
    elif state != 'draft':
        at = last_submit.actioned_at if last_submit else expense.created_at
        app_col.update(state='src', date_text=_date_text(at), stamp=_make_stamp(applicant, at))
    columns.append(app_col)

    # ── 承認ルート（全履歴 + 承認予定者） ──
    route = []
    prev_at = None
    for a in actions:
        code = _code(a)
        if code == 'DRAFT':
            continue
        st = _ACTION_STATE.get(code)
        if st is None:
            continue
        so = _step_order(a)
        user = a.approver_man_number
        post = _post_name(user)
        if st == 'src':
            title_text = '申請'
        else:
            title_text = '・'.join(x for x in (_role(so), post) if x)
        pill = _PILL_LABEL[st]
        item = {
            'state': st,
            'step_order': pos_by_order.get(so, so),
            'title': title_text,
            'pill': pill,
            'user_name': _user_name(user),
            'post_name': post,
            'datetime_text': _datetime_text(a.actioned_at),
            'comment': (a.comment or '').strip() if st in ('done', 'return', 'reject') else '',
            'elapsed_text': '',
            'pct': 0,
        }
        if st in ('done', 'return', 'reject') and prev_at is not None:
            item['elapsed_text'] = f"{_elapsed_text(prev_at, a.actioned_at)}で{pill}"
            item['pct'] = _elapsed_pct(prev_at, a.actioned_at)
        route.append(item)
        prev_at = a.actioned_at

    if state == 'wait':
        for p in pending:
            so = p.step_order
            st = 'now' if so == now_order else 'wait'
            post = _post_name(p.man_number)
            item = {
                'state': st,
                'step_order': pos_by_order.get(so, so),
                'title': '・'.join(x for x in (_role(so), post or _user_name(p.man_number)) if x),
                'pill': _PILL_LABEL[st],
                'user_name': _user_name(p.man_number),
                'post_name': post,
                'datetime_text': '',
                'comment': '',
                'elapsed_text': '',
                'pct': 0,
            }
            if st == 'now' and last_event_at is not None:
                item['elapsed_text'] = f"経過 {_elapsed_text(last_event_at, now)} / 目安{ELAPSED_FULL_DAYS:g}日"
                item['pct'] = _elapsed_pct(last_event_at, now)
            route.append(item)

    return {
        'state': state,
        'title': title,
        'current': current,
        'total': total,
        'next_label': next_label,
        'completed_text': completed_text,
        'segments': segments,
        'columns': columns,
        'route': route,
    }
