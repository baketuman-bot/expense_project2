"""承認欄（印鑑テーブル）・決裁状況バー用データ構築 build_approval_board のテスト。

DBに依存しない純粋関数なので SimpleNamespace のフェイクで検証する。
"""
from datetime import datetime, timedelta, timezone as dt_tz
from types import SimpleNamespace as NS

from django.test import SimpleTestCase

from expenses.approval_board import build_approval_board, stamp_name, stamp_date, stamp_post


JST = dt_tz(timedelta(hours=9))


def _t(day, hour=10, minute=0):
    return datetime(2026, 9, day, hour, minute, tzinfo=JST)


def _user(name, post):
    return NS(user_name=name, post_cd=NS(post_name=post) if post else None)


def _status(cd, name, action=None):
    return NS(status_cd=cd, status_name=name, action_name=action)


def _act(cd, step_order, user, at, comment=None):
    return NS(
        action_status=_status(cd, cd, cd),
        step=NS(step_order=step_order) if step_order else None,
        approver_man_number=user,
        actioned_at=at,
        comment=comment,
    )


def _pending(step_order, user):
    return NS(step_order=step_order, man_number=user)


APPLICANT = _user('山田 太郎', '営業部')
S1 = _user('佐藤 健一', '営業部 部長')
S2 = _user('鈴木 一郎', '営業本部 本部長')
KEIRI = _user('高橋 美咲', '経理部')
KEIRI_LABEL = NS(user_name='経理部門', post_cd=NS(post_name=''))

STEPS = [
    NS(step_order=1, approver_post=NS(post_name='部長'), allowed_bumon_scope='same'),
    NS(step_order=2, approver_post=NS(post_name='本部長'), allowed_bumon_scope='parent'),
    NS(step_order=3, approver_post=None, allowed_bumon_scope='keiri'),
]


def _doc(status_cd):
    return NS(status_cd=NS(status_cd=status_cd), man_number=APPLICANT, created_at=_t(22, 9, 40))


class StampHelpersTest(SimpleTestCase):
    def test_stamp_name_uses_family_name(self):
        self.assertEqual(stamp_name('山田 太郎'), '山田')
        self.assertEqual(stamp_name('山田　太郎'), '山田')

    def test_stamp_name_without_space_falls_back_to_two_chars(self):
        self.assertEqual(stamp_name('経理部門'), '経理')
        self.assertEqual(stamp_name('高橋'), '高橋')
        self.assertEqual(stamp_name(''), '')

    def test_stamp_date_short_format(self):
        self.assertEqual(stamp_date(_t(3, 11, 5)), '26.9.3')

    def test_stamp_post_aliases_ippan_shain_to_tanto(self):
        self.assertEqual(stamp_post('一般社員'), '担当')
        self.assertEqual(stamp_post('営業部 部長'), '営業部 部長')
        self.assertEqual(stamp_post(None), '')

    def test_stamp_top_uses_alias(self):
        staff = _user('中尾 祥吾', '一般社員')
        actions = [
            _act('INPRO', 1, staff, _t(22, 9, 40)),
            _act('APPROVED', 1, staff, _t(23, 11, 5)),
        ]
        doc = NS(status_cd=NS(status_cd='APPROVED'), man_number=staff, created_at=_t(22))
        board = build_approval_board(doc, actions, [_pending(2, S2)], STEPS, now=_t(24))
        self.assertEqual(board['columns'][3]['stamp']['top'], '担当')   # 申請者印
        self.assertEqual(board['columns'][2]['stamp']['top'], '担当')   # 1段目の承認印
        # 承認欄ヘッダーの役職表示は言い換えない
        self.assertEqual(board['columns'][2]['cap'], '一般社員')


class WaitingBoardTest(SimpleTestCase):
    """1段目承認済み・2段目待ち"""

    def setUp(self):
        actions = [
            _act('INPRO', 1, APPLICANT, _t(22, 9, 40), '申請者による提出'),
            _act('APPROVED', 1, S1, _t(23, 11, 5)),
        ]
        pending = [_pending(2, S2), _pending(3, KEIRI_LABEL)]
        self.board = build_approval_board(
            _doc('APPROVED'), actions, pending, STEPS,
            progress={'current': 1, 'total': 3}, now=_t(24, 9, 0),
        )

    def test_state_and_title(self):
        self.assertEqual(self.board['state'], 'wait')
        self.assertEqual(self.board['title'], '2段目で承認待ち')
        self.assertEqual(self.board['current'], 1)
        self.assertEqual(self.board['total'], 3)
        self.assertEqual(self.board['next_label'], '鈴木 一郎（営業本部 本部長）')

    def test_segments(self):
        self.assertEqual([s['state'] for s in self.board['segments']], ['done', 'now', 'wait'])
        self.assertEqual([s['label'] for s in self.board['segments']], ['部長', '本部長', '経理部門'])

    def test_columns_are_highest_step_first_then_applicant(self):
        cols = self.board['columns']
        self.assertEqual([c['role'] for c in cols], ['決裁', '2段目', '1段目', '申請者'])
        self.assertEqual([c['state'] for c in cols], ['wait', 'now', 'done', 'src'])
        self.assertEqual(cols[0]['cap'], '経理部門')
        self.assertEqual(cols[0]['user_name'], '経理部門')
        self.assertEqual(cols[1]['user_name'], '鈴木 一郎')
        self.assertIsNone(cols[1]['stamp'])

    def test_done_column_has_stamp_with_post_name(self):
        col = self.board['columns'][2]
        self.assertEqual(col['stamp'], {'top': '営業部 部長', 'date': '26.9.23', 'name': '佐藤'})
        self.assertEqual(col['date_text'], '9月23日')

    def test_applicant_column_stamp(self):
        col = self.board['columns'][3]
        self.assertEqual(col['cap'], '起案')
        self.assertEqual(col['stamp'], {'top': '営業部', 'date': '26.9.22', 'name': '山田'})

    def test_now_column_elapsed_pct(self):
        # 9/23 11:05 → 9/24 09:00 = 約0.91日 / 目安2日 = 45%
        col = self.board['columns'][1]
        self.assertEqual(col['pct'], 45)

    def test_route_items(self):
        route = self.board['route']
        self.assertEqual([r['state'] for r in route], ['src', 'done', 'now', 'wait'])
        self.assertEqual(route[0]['title'], '申請')
        self.assertEqual(route[1]['title'], '1段目・営業部 部長')
        self.assertEqual(route[1]['datetime_text'], '9月23日 11:05')
        self.assertEqual(route[2]['pill'], '承認待ち')
        self.assertEqual(route[3]['pill'], '未着手')
        self.assertEqual(route[3]['title'], '決裁・経理部門')


class DoneBoardTest(SimpleTestCase):
    def test_all_stamped(self):
        actions = [
            _act('INPRO', 1, APPLICANT, _t(22, 9, 40)),
            _act('APPROVED', 1, S1, _t(23, 11, 5)),
            _act('APPROVED', 2, S2, _t(23, 16, 30), '内容確認しました。'),
            _act('FNS', 3, KEIRI, _t(24, 10, 12)),
        ]
        board = build_approval_board(_doc('FNS'), actions, [], STEPS, now=_t(25))
        self.assertEqual(board['state'], 'done')
        self.assertEqual(board['title'], '決裁済み')
        self.assertEqual(board['current'], 3)
        self.assertEqual([c['state'] for c in board['columns']], ['done', 'done', 'done', 'src'])
        self.assertEqual(board['columns'][0]['stamp']['name'], '高橋')
        self.assertEqual(board['completed_text'], '9月24日 完了')
        self.assertEqual(board['route'][2]['comment'], '内容確認しました。')


class ReturnedBoardTest(SimpleTestCase):
    def test_returned_at_step1(self):
        actions = [
            _act('INPRO', 1, APPLICANT, _t(22, 9, 40)),
            _act('RETURNED', 1, S1, _t(23, 11, 5), '宛名を直してください。'),
        ]
        # 差戻し後も T_DocumentApprover に pending が残っている場合を想定
        pending = [_pending(1, S1), _pending(2, S2)]
        board = build_approval_board(_doc('RETURNED'), actions, pending, STEPS, now=_t(24))
        self.assertEqual(board['state'], 'return')
        self.assertEqual(board['title'], '1段目で差戻し')
        self.assertEqual([c['state'] for c in board['columns']], ['wait', 'wait', 'return', 'src'])
        self.assertEqual(board['columns'][2]['stamp'], {'top': '営業部 部長', 'date': '26.9.23', 'name': '佐藤'})
        self.assertEqual([s['state'] for s in board['segments']], ['return', 'wait', 'wait'])
        self.assertIsNone(board['next_label'])

    def test_resubmitted_after_return_restarts_cycle(self):
        actions = [
            _act('INPRO', 1, APPLICANT, _t(22, 9, 40)),
            _act('APPROVED', 1, S1, _t(23, 11, 5)),
            _act('RETURNED', 2, S2, _t(23, 15, 0), '再確認'),
            _act('INPRO', 1, APPLICANT, _t(24, 9, 0), '申請者による再提出'),
        ]
        pending = [_pending(1, S1), _pending(2, S2), _pending(3, KEIRI_LABEL)]
        board = build_approval_board(_doc('INPRO'), actions, pending, STEPS, now=_t(24, 12))
        self.assertEqual(board['title'], '1段目で承認待ち')
        # 前サイクルの承認・差戻しは承認欄に反映しない
        self.assertEqual([c['state'] for c in board['columns']], ['wait', 'wait', 'now', 'src'])
        self.assertEqual(board['columns'][3]['stamp']['date'], '26.9.24')
        self.assertEqual(board['current'], 0)
        # 履歴（承認ルート）には前サイクルも残す
        self.assertEqual(len(board['route']), 4 + 3)


class RejectedAndCancelledBoardTest(SimpleTestCase):
    def test_rejected_at_step2(self):
        actions = [
            _act('INPRO', 1, APPLICANT, _t(22, 9, 40)),
            _act('APPROVED', 1, S1, _t(23, 11, 5)),
            _act('REJECTED', 2, S2, _t(24, 9, 15), '予算超過'),
        ]
        board = build_approval_board(_doc('REJECTED'), actions, [], STEPS, now=_t(25))
        self.assertEqual(board['state'], 'reject')
        self.assertEqual(board['title'], '2段目で却下')
        self.assertEqual([c['state'] for c in board['columns']], ['wait', 'reject', 'done', 'src'])
        self.assertEqual(board['current'], 1)

    def test_cancelled_by_applicant(self):
        actions = [
            _act('INPRO', 1, APPLICANT, _t(22, 9, 40)),
            _act('CANCEL', 1, APPLICANT, _t(22, 15, 0), '申請者による取り消し'),
        ]
        board = build_approval_board(_doc('CANCEL'), actions, [], STEPS, now=_t(25))
        self.assertEqual(board['state'], 'cancel')
        self.assertEqual(board['title'], '取り消し済み')
        self.assertEqual(board['columns'][3]['state'], 'cancel')
        self.assertEqual(board['columns'][3]['stamp']['date'], '26.9.22')

    def test_draft_has_no_stamps(self):
        board = build_approval_board(_doc('DRAFT'), [], [], STEPS, now=_t(25))
        self.assertEqual(board['state'], 'draft')
        self.assertEqual(board['title'], '下書き')
        self.assertEqual(board['columns'][3]['state'], 'draft')
        self.assertIsNone(board['columns'][3]['stamp'])
        self.assertEqual(board['route'], [])


class EdgeCaseTest(SimpleTestCase):
    def test_no_steps_returns_none(self):
        self.assertIsNone(build_approval_board(_doc('INPRO'), [], [], [], now=_t(25)))

    def test_action_without_step_is_ignored_for_columns(self):
        actions = [
            _act('INPRO', None, APPLICANT, _t(22, 9, 40)),
            _act('APPROVED', None, S1, _t(23, 11, 5)),
        ]
        board = build_approval_board(_doc('APPROVED'), actions, [_pending(2, S2)], STEPS, now=_t(24))
        self.assertEqual([c['state'] for c in board['columns']], ['wait', 'now', 'wait', 'src'])

    def test_draft_actions_are_excluded_from_route(self):
        actions = [
            _act('DRAFT', 1, APPLICANT, _t(21, 9, 0), '下書き保存'),
            _act('INPRO', 1, APPLICANT, _t(22, 9, 40)),
        ]
        board = build_approval_board(_doc('INPRO'), actions, [_pending(1, S1)], STEPS, now=_t(22, 12))
        self.assertEqual([r['state'] for r in board['route']], ['src', 'now'])

    def test_gapped_step_orders_are_shown_positionally(self):
        """本番の step_order は 1,2,5 のような飛び番 → 表示は 1,2,3段目（最終は決裁）"""
        steps = [
            NS(step_order=1, approver_post=NS(post_name='課長'), allowed_bumon_scope='same'),
            NS(step_order=2, approver_post=NS(post_name='統括'), allowed_bumon_scope='parent'),
            NS(step_order=5, approver_post=NS(post_name='担当部長'), allowed_bumon_scope='keiri'),
        ]
        actions = [
            _act('INPRO', 1, APPLICANT, _t(22, 9, 40)),
            _act('APPROVED', 1, S1, _t(23, 11, 5)),
            _act('APPROVED', 2, S2, _t(23, 12, 0)),
        ]
        board = build_approval_board(_doc('APPROVED'), actions, [_pending(5, KEIRI_LABEL)], steps, now=_t(24))
        self.assertEqual(board['title'], '3段目で承認待ち')
        self.assertEqual([c['role'] for c in board['columns']], ['決裁', '2段目', '1段目', '申請者'])
        self.assertEqual(board['route'][3]['title'], '決裁・経理部門')
        self.assertEqual(board['route'][3]['step_order'], 3)
        self.assertEqual(board['route'][1]['pill'], '承認済み')
        self.assertEqual(board['route'][2]['elapsed_text'], '55分で承認済み')

    def test_long_post_name_is_flagged_for_shrink(self):
        long_post = _user('渡辺 一', '営業本部 第一営業部 部長')
        actions = [
            _act('INPRO', 1, APPLICANT, _t(22, 9, 40)),
            _act('APPROVED', 1, long_post, _t(23, 11, 5)),
        ]
        board = build_approval_board(_doc('APPROVED'), actions, [_pending(2, S2)], STEPS, now=_t(24))
        self.assertEqual(board['columns'][2]['stamp']['top'], '営業本部 第一営業部 部長')
