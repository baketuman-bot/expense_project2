"""仕訳明細の分割機能（split_from）のテスト"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from expenses.models import (
    M_Account, M_DocumentGroup, M_DocumentType, M_Status,
    T_Document, T_DocumentContent,
)

User = get_user_model()


class JournalSplitFixtureMixin:
    """FNS済み申請 + 仕訳対象の元明細1件を作る共通フィクスチャ"""

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
        cls.account2, _ = M_Account.objects.get_or_create(
            account_cd='671', defaults={'account_name': '交際費'}
        )
        cls.user, _ = User.objects.get_or_create(
            man_number='JSP001',
            defaults={'username': 'journal_split_user', 'user_name': '仕訳太郎'},
        )
        cls.doc = T_Document.objects.create(
            document_type=cls.doc_type,
            title='仕訳分割テスト申請',
            man_number=cls.user,
            status_cd=cls.status_fns,
        )
        # 内税・税込11,000円（消費税1,000円）の元明細
        cls.parent = T_DocumentContent.objects.create(
            document=cls.doc,
            date='2026-07-01',
            account=cls.account,
            amount=Decimal('11000'),
            consumption_tax=Decimal('1000'),
            consumption_kbn=0,
            settle_kbn='CAS_INPRO',
            purpose='会議費用',
            shiharaisaki='テスト商店',
        )

    def _create_split(self, **extra):
        """元明細から分割行を直接作る（APIを介さないテスト用ヘルパ）"""
        defaults = dict(
            document=self.doc, date='2026-07-01', account=self.account,
            settle_kbn='CAS_INPRO', purpose='会議費用', shiharaisaki='テスト商店',
            consumption_kbn=0, split_from=self.parent,
        )
        defaults.update(extra)
        return T_DocumentContent.all_objects.create(**defaults)


class SplitFromModelTest(JournalSplitFixtureMixin, TestCase):
    """split_from フィールドとマネージャのテスト"""

    def test_split_from_field_exists(self):
        field = T_DocumentContent._meta.get_field('split_from')
        self.assertTrue(field.null)
        self.assertEqual(field.remote_field.model, T_DocumentContent)
        self.assertEqual(field.db_column, 'split_from_id')

    def test_default_manager_excludes_split_rows(self):
        split = self._create_split()
        pks = set(T_DocumentContent.objects.values_list('document_detail_id', flat=True))
        self.assertIn(self.parent.pk, pks)
        self.assertNotIn(split.pk, pks)

    def test_all_objects_includes_split_rows(self):
        split = self._create_split()
        pks = set(T_DocumentContent.all_objects.values_list('document_detail_id', flat=True))
        self.assertIn(split.pk, pks)

    def test_related_manager_excludes_split_rows(self):
        """申請詳細・合計計算が使う doc.contents に分割行が現れないこと"""
        split = self._create_split()
        pks = [c.pk for c in self.doc.contents.all()]
        self.assertIn(self.parent.pk, pks)
        self.assertNotIn(split.pk, pks)

    def test_split_rows_fetchable_via_all_objects_filter(self):
        """parent.splits はデフォルトマネージャの影響で常に空になるため使わない。
        分割行の取得は all_objects.filter(split_from=...) を使う"""
        split = self._create_split()
        got = list(T_DocumentContent.all_objects.filter(split_from=self.parent))
        self.assertEqual([split.pk], [s.pk for s in got])


class ViewSqlSplitFromTest(TestCase):
    """DBビュー定義に split_from_id が含まれること"""

    def test_v_documentcontents_has_split_from(self):
        from expenses.view_sqls import _V_DOCUMENTCONTENTS
        self.assertIn('dc.split_from_id', _V_DOCUMENTCONTENTS)

    def test_v_journaldocuments_has_split_from(self):
        from expenses.view_sqls import _V_JOURNALDOCUMENTS
        self.assertIn('vdc.split_from_id', _V_JOURNALDOCUMENTS)


class JournalSplitApiTest(JournalSplitFixtureMixin, TestCase):
    """分割作成・削除APIのテスト"""

    def setUp(self):
        self.client.force_login(self.user)

    def test_split_creates_row(self):
        res = self.client.post(f'/settings/settlement/journal/{self.parent.pk}/split/')
        self.assertEqual(res.status_code, 200)
        d = res.json()
        self.assertTrue(d['ok'])
        split = T_DocumentContent.all_objects.get(pk=d['row']['pk'])
        self.assertEqual(split.split_from_id, self.parent.pk)
        self.assertEqual(split.settle_kbn, 'CAS_INPRO')
        self.assertEqual(split.account_id, '670')
        self.assertIsNone(split.amount)            # 申請金額はコピーしない
        self.assertIsNone(split.consumption_tax)   # 消費税もコピーしない
        self.assertFalse(split.journal_done)
        self.assertEqual(d['row']['parent_pk'], self.parent.pk)

    def test_split_of_split_returns_400(self):
        split = self._create_split()
        res = self.client.post(f'/settings/settlement/journal/{split.pk}/split/')
        self.assertEqual(res.status_code, 400)

    def test_split_requires_post(self):
        res = self.client.get(f'/settings/settlement/journal/{self.parent.pk}/split/')
        self.assertEqual(res.status_code, 405)

    def test_delete_split_row(self):
        split = self._create_split()
        res = self.client.post(f'/settings/settlement/journal/{split.pk}/delete/')
        self.assertEqual(res.status_code, 200)
        self.assertFalse(T_DocumentContent.all_objects.filter(pk=split.pk).exists())

    def test_delete_parent_returns_400_and_keeps_row(self):
        res = self.client.post(f'/settings/settlement/journal/{self.parent.pk}/delete/')
        self.assertEqual(res.status_code, 400)
        self.assertTrue(T_DocumentContent.all_objects.filter(pk=self.parent.pk).exists())
