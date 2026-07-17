"""取込済みデータ検索（settlement_imported）と
仕訳作成/債務管理データ作成リストからの journal_done=2 除外のテスト。
"""
import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from expenses.models import (
    M_Account, M_DocumentGroup, M_DocumentType, M_Status,
    T_Document, T_DocumentContent,
)

User = get_user_model()

URL = '/settings/settlement/imported/'


class SettlementImportedTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.status_fns, _ = M_Status.objects.get_or_create(
            status_cd='FNS', defaults={'status_name': '最終承認'}
        )
        grp, _ = M_DocumentGroup.objects.get_or_create(
            menu_group='PAY',
            defaults={'menu_group_name': '支出伺い', 'category': 'expense', 'menu_order': 1},
        )
        cls.doc_type, _ = M_DocumentType.objects.get_or_create(
            document_type_id=1,
            defaults={'document_type_name': 'テスト種別', 'menu_group': grp},
        )
        cls.account, _ = M_Account.objects.get_or_create(
            account_cd='670', defaults={'account_name': '旅費交通費'}
        )
        cls.user, _ = User.objects.get_or_create(
            man_number='SIM001',
            defaults={'username': 'settlement_imported_user', 'user_name': '検索太郎'},
        )

    def setUp(self):
        self.client.force_login(self.user)

    def _doc(self, settled_at=datetime.datetime(2026, 7, 10, 0, 0, 0)):
        return T_Document.objects.create(
            document_type=self.doc_type, title='申請', man_number=self.user,
            status_cd=self.status_fns, settled_at=settled_at,
        )

    def _content(self, doc, **extra):
        defaults = dict(
            document=doc, date=datetime.date(2026, 7, 1), account=self.account,
            settle_kbn='CAS_INPRO', journal_done=2,
            journal_at=datetime.datetime(2026, 7, 15, 9, 30, 0),
            journal_amont=Decimal('1000'),
        )
        defaults.update(extra)
        return T_DocumentContent.objects.create(**defaults)

    def test_entry_lists_exclude_imported(self):
        """仕訳作成/債務管理データ作成のリストに journal_done=2 の明細が含まれないこと"""
        doc = self._doc()
        done1 = self._content(doc, journal_done=1, journal_at=None)
        done2 = self._content(doc)
        lon2  = self._content(doc, settle_kbn='LON_INPRO')

        res = self.client.get('/settings/settlement/journal/entry/')
        self.assertContains(res, f'jnl-item-{done1.pk}')
        self.assertNotContains(res, f'jnl-item-{done2.pk}')

        res = self.client.get('/settings/settlement/debt/entry/')
        # LON側は journal_done=2 のみ → 対象なしで精算メニューへリダイレクト
        self.assertEqual(res.status_code, 302)
        lon1 = self._content(doc, settle_kbn='LON_INPRO', journal_done=1, journal_at=None)
        res = self.client.get('/settings/settlement/debt/entry/')
        self.assertContains(res, f'jnl-item-{lon1.pk}')
        self.assertNotContains(res, f'jnl-item-{lon2.pk}')

    def test_search_requires_button_and_filters(self):
        """検索前は一覧なし。検索後は 伝票日付・journal_at・精算方法・申請ID でフィルタされること"""
        doc_a = self._doc(settled_at=datetime.datetime(2026, 7, 10, 0, 0, 0))
        a = self._content(doc_a)   # CAS, 伝票 7/10, 取込 7/15
        doc_b = self._doc(settled_at=datetime.datetime(2026, 7, 20, 0, 0, 0))
        b = self._content(doc_b, settle_kbn='LON_INPRO',
                          journal_at=datetime.datetime(2026, 7, 16, 10, 0, 0))

        # 検索ボタンなし → 一覧なし
        res = self.client.get(URL)
        self.assertNotContains(res, f'value="{a.pk}"')

        # 検索（条件なし）→ 両方
        res = self.client.get(URL, {'search': '1'})
        self.assertContains(res, f'value="{a.pk}"')
        self.assertContains(res, f'value="{b.pk}"')

        # 精算方法
        res = self.client.get(URL, {'search': '1', 'settle_kbn': 'LON_INPRO'})
        self.assertNotContains(res, f'value="{a.pk}"')
        self.assertContains(res, f'value="{b.pk}"')

        # 申請ID
        res = self.client.get(URL, {'search': '1', 'document_id': doc_a.document_id})
        self.assertContains(res, f'value="{a.pk}"')
        self.assertNotContains(res, f'value="{b.pk}"')

        # 伝票日付（7/15まで → doc_a のみ）
        res = self.client.get(URL, {'search': '1', 'vdate_to': '2026-07-15'})
        self.assertContains(res, f'value="{a.pk}"')
        self.assertNotContains(res, f'value="{b.pk}"')

        # 取込日（7/16以降 → b のみ）
        res = self.client.get(URL, {'search': '1', 'journal_at_from': '2026-07-16'})
        self.assertNotContains(res, f'value="{a.pk}"')
        self.assertContains(res, f'value="{b.pk}"')

    def test_revert_sets_journal_done_1_and_reappears(self):
        """チェックした行の実行で journal_done=1・journal_at クリアになり、作成リストに再表示されること"""
        doc = self._doc()
        c = self._content(doc)
        split = T_DocumentContent.all_objects.create(
            document=doc, split_from=c, account=self.account,
            settle_kbn='CAS_INPRO', journal_done=2,
            journal_at=datetime.datetime(2026, 7, 15, 9, 30, 0),
            journal_amont=Decimal('500'), date=datetime.date(2026, 7, 1),
        )

        res = self.client.post(URL, {'ids': [str(c.pk)], 'query': 'search=1'})
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res['Location'].endswith('?search=1'))

        c.refresh_from_db()
        split.refresh_from_db()
        self.assertEqual(c.journal_done, 1)
        self.assertIsNone(c.journal_at)
        self.assertEqual(split.journal_done, 1)
        self.assertIsNone(split.journal_at)

        # 仕訳作成リストに再表示される
        res = self.client.get('/settings/settlement/journal/entry/')
        self.assertContains(res, f'jnl-item-{c.pk}')
