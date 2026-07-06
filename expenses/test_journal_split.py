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


class JournalSaveSplitTest(JournalSplitFixtureMixin, TestCase):
    """journal_save の分割行対応テスト"""

    def setUp(self):
        self.client.force_login(self.user)
        self.split = self._create_split()

    def _post(self, pk, **extra):
        data = {
            'journal_amont':           '3000',
            'consumption_tax':         '300',
            'journal_tax_kbn':         '312',
            'journal_tax_rate':        '10%',
            'journal_discription_deb': 'テスト適用',
        }
        data.update(extra)
        return self.client.post(f'/settings/settlement/journal/{pk}/save/', data)

    def test_split_row_done_without_credit(self):
        """分割行は貸方なしで journal_done=True になる"""
        res = self._post(self.split.pk)
        self.assertTrue(res.json()['journal_done'])

    def test_parent_still_requires_credit(self):
        """元行は従来どおり貸方必須"""
        res = self._post(self.parent.pk)
        self.assertFalse(res.json()['journal_done'])
        fields = {m['field'] for m in res.json()['missing']}
        self.assertIn('account_cd_cre', fields)

    def test_split_account_cd_updated(self):
        """分割行のみ借方科目を変更できる"""
        self._post(self.split.pk, account_cd='671')
        s = T_DocumentContent.all_objects.get(pk=self.split.pk)
        self.assertEqual(s.account_id, '671')

    def test_parent_account_cd_ignored(self):
        """元行への account_cd POST は無視される"""
        self._post(self.parent.pk, account_cd='671')
        p = T_DocumentContent.all_objects.get(pk=self.parent.pk)
        self.assertEqual(p.account_id, '670')

    def test_credit_posted_to_split_is_ignored(self):
        """分割行に貸方値をPOSTしても保存されない"""
        self._post(self.split.pk, account_cd_cre='41400', journal_amount_cre='999',
                   journal_discription_cre='貸方摘要')
        s = T_DocumentContent.all_objects.get(pk=self.split.pk)
        self.assertIsNone(s.account_cd_cre)
        self.assertIsNone(s.journal_amount_cre)
        self.assertIsNone(s.journal_discription_cre)

    def test_group_mismatch_flag(self):
        """元行+分割行の借方合計 ≠ 税込金額のとき mismatch=True。
        フィクスチャは内税・税込11,000円なので期待値は11,000"""
        # 元行 7,000+700 / 分割 3,000+300 → 合計 11,000 → 一致
        self._post(self.parent.pk, journal_amont='7000', consumption_tax='700',
                   account_cd_cre='41400', journal_amount_cre='7700',
                   journal_discription_cre='摘要')
        res = self._post(self.split.pk)
        self.assertFalse(res.json()['group']['mismatch'])
        # 分割を 4,000+400 に変更 → 合計 12,100 → 不一致
        res = self._post(self.split.pk, journal_amont='4000', consumption_tax='400')
        self.assertTrue(res.json()['group']['mismatch'])


class JournalDetailApiSplitTest(JournalSplitFixtureMixin, TestCase):
    """journal_detail_api の分割行対応テスト"""

    def setUp(self):
        self.client.force_login(self.user)
        self.split = self._create_split()

    def test_split_detail_flags(self):
        res = self.client.get(f'/settings/settlement/journal/{self.split.pk}/')
        self.assertEqual(res.status_code, 200)
        d = res.json()
        self.assertTrue(d['is_split'])
        self.assertEqual(d['parent_pk'], self.parent.pk)
        self.assertEqual(d['account_cd_raw'], '670')

    def test_split_ref_amount_comes_from_parent(self):
        """分割行の参照エリアには元行の申請金額を表示する"""
        res = self.client.get(f'/settings/settlement/journal/{self.split.pk}/')
        d = res.json()
        self.assertTrue(d['ref']['amount'].startswith('11000'))
        self.assertTrue(d['ref']['consumption_tax'].startswith('1000'))

    def test_split_manual_defaults_are_empty(self):
        """分割行の手入力エリアデフォルトは空（金額は手入力前提）"""
        res = self.client.get(f'/settings/settlement/journal/{self.split.pk}/')
        d = res.json()
        self.assertEqual(d['default_journal_amont'], '')

    def test_parent_detail_is_not_split(self):
        res = self.client.get(f'/settings/settlement/journal/{self.parent.pk}/')
        d = res.json()
        self.assertFalse(d['is_split'])
        self.assertTrue(d['group']['has_split'])

    def test_hojo_options_account_cd_override(self):
        """?account_cd= で補助科目候補の科目を切り替えられる"""
        from expenses.models import M_AccountSub
        M_AccountSub.objects.get_or_create(
            account_cd='671', sub_account_cd='01',
            defaults={'sub_account_name': 'テスト補助'},
        )
        res = self.client.get(
            f'/settings/settlement/journal/{self.split.pk}/?account_cd=671')
        d = res.json()
        self.assertEqual(d['hojo_options'][0]['cd'], '01')


class JournalEntryViewSplitTest(JournalSplitFixtureMixin, TestCase):
    """journal_entry ビューの分割行対応テスト"""

    def setUp(self):
        self.client.force_login(self.user)
        self.split = self._create_split()

    def test_split_rows_follow_parent(self):
        """?ids= に元行だけ指定しても分割行が直後に並ぶ"""
        res = self.client.get(
            f'/settings/settlement/journal/entry/?ids={self.parent.pk}')
        self.assertEqual(res.status_code, 200)
        rows = res.context['rows']
        pks = [r['pk'] for r in rows]
        self.assertEqual(pks.index(self.split.pk), pks.index(self.parent.pk) + 1)
        by_pk = {r['pk']: r for r in rows}
        self.assertTrue(by_pk[self.split.pk]['is_split'])
        self.assertEqual(by_pk[self.split.pk]['parent_pk'], self.parent.pk)
        self.assertFalse(by_pk[self.parent.pk]['is_split'])

    def test_account_options_in_context(self):
        res = self.client.get(
            f'/settings/settlement/journal/entry/?ids={self.parent.pk}')
        cds = [a['account_cd'] for a in res.context['account_options']]
        self.assertIn('670', cds)
        self.assertIn('671', cds)

    def test_total_includes_splits(self):
        res = self.client.get(
            f'/settings/settlement/journal/entry/?ids={self.parent.pk}')
        self.assertEqual(res.context['total'], 2)


class JournalEntryTemplateSplitTest(JournalSplitFixtureMixin, TestCase):
    """分割UIがテンプレートに含まれることのスモークテスト"""

    def setUp(self):
        self.client.force_login(self.user)
        self.split = self._create_split()

    def test_template_has_split_ui(self):
        res = self.client.get(
            f'/settings/settlement/journal/entry/?ids={self.parent.pk}')
        html = res.content.decode('utf-8')
        self.assertIn('jnlSplit(', html)          # 分割ボタン
        self.assertIn('jnlSplitDelete(', html)    # 削除ボタン
        self.assertIn('inp-account-cd', html)     # 借方科目セレクト
        self.assertIn('jnl-cre-section', html)    # 貸方セクションのラッパ
        self.assertIn('↳ 分割', html)             # 分割行のインジケータ


class JournalCsvSplitTest(JournalSplitFixtureMixin, TestCase):
    """journal_csv（Excel出力）の分割行対応テスト"""

    def setUp(self):
        self.client.force_login(self.user)
        # 元行: 入力済み（借方+貸方）
        self.parent.journal_amont = Decimal('7000')
        self.parent.journal_tax = Decimal('700')
        self.parent.journal_tax_kbn = '312'
        self.parent.journal_tax_rate = '10%'
        self.parent.journal_discription_deb = '元行適用'
        self.parent.account_cd_cre = '41400'
        self.parent.journal_amount_cre = Decimal('11000')
        self.parent.journal_discription_cre = '貸方摘要'
        self.parent.journal_done = True
        self.parent.save()
        # 分割行: 入力済み（借方のみ・科目変更あり）
        self.split = self._create_split(
            account=self.account2,
            journal_amont=Decimal('3000'), journal_tax=Decimal('300'),
            journal_tax_kbn='312', journal_tax_rate='10%',
            journal_discription_deb='分割適用', journal_done=True,
        )

    def _load_rows(self, res):
        from io import BytesIO
        import openpyxl
        wb = openpyxl.load_workbook(BytesIO(res.content))
        ws = wb.active
        return list(ws.iter_rows(min_row=2, values_only=True))

    def test_split_row_included_after_parent(self):
        """元行のidだけ指定しても分割行が直後に出力される"""
        res = self.client.get(
            f'/settings/settlement/journal/csv/?ids={self.parent.pk}')
        self.assertEqual(res.status_code, 200)
        data = self._load_rows(res)
        # 列2 = 申請明細番号（document_detail_id）
        detail_ids = [row[2] for row in data]
        self.assertEqual(detail_ids, [self.parent.pk, self.split.pk])

    def test_split_row_uses_own_account(self):
        res = self.client.get(
            f'/settings/settlement/journal/csv/?ids={self.parent.pk},{self.split.pk}')
        data = self._load_rows(res)
        # 列10 = 科目名。分割行は変更後の科目（交際費）
        self.assertEqual(data[1][10], '交際費')


class SettlementJournalListSplitTest(JournalSplitFixtureMixin, TestCase):
    """仕訳出力一覧の分割行対応テスト"""

    def setUp(self):
        self.client.force_login(self.user)
        self.parent.journal_done = True
        self.parent.save()

    def test_done_split_follows_parent(self):
        split = self._create_split(journal_done=True)
        res = self.client.get('/settings/settlement/journal/')
        rows = res.context['rows']
        pks = [r['content'].pk for r in rows]
        self.assertEqual(pks.index(split.pk), pks.index(self.parent.pk) + 1)
        by_pk = {r['content'].pk: r for r in rows}
        self.assertTrue(by_pk[split.pk]['is_split'])

    def test_group_with_undone_split_excluded(self):
        """分割行が未入力のグループは（不完全な仕訳のため）一覧に出さない"""
        self._create_split(journal_done=False)
        res = self.client.get('/settings/settlement/journal/')
        pks = [r['content'].pk for r in res.context['rows']]
        self.assertNotIn(self.parent.pk, pks)
