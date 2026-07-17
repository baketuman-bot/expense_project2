"""仕訳/債務管理CSV出力後の精算処理完了API（journal_complete / debt_complete）のテスト。

- 対象明細の journal_done=2（仕訳取込済み）・journal_at=実行日時 がセットされる
- 選択した元行の分割行も併せて仕訳取込済みになる
- journal_done=2 の行は出力一覧・CSV対象（journal_done=1）から外れる
- GET は 405、ids 未指定は 400
"""
import datetime
from decimal import Decimal
from io import StringIO
import csv as _csv

from django.contrib.auth import get_user_model
from django.test import TestCase

from expenses.models import (
    M_Account, M_DocumentGroup, M_DocumentType, M_Status,
    T_Document, T_DocumentContent,
)

User = get_user_model()


class JournalCompleteTest(TestCase):
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
            man_number='JCP001',
            defaults={'username': 'journal_complete_user', 'user_name': '取込太郎'},
        )

    def setUp(self):
        self.client.force_login(self.user)

    def _doc(self, title='申請'):
        return T_Document.objects.create(
            document_type=self.doc_type, title=title, man_number=self.user,
            status_cd=self.status_fns,
            settled_at=datetime.datetime(2026, 7, 10, 0, 0, 0),
        )

    def _content(self, doc, **extra):
        defaults = dict(
            document=doc, date=datetime.date(2026, 7, 1), account=self.account,
            settle_kbn='CAS_INPRO', journal_done=1,
            journal_amont=Decimal('1000'), journal_tax=Decimal('100'),
            journal_tax_kbn='312', journal_tax_rate='10%',
            journal_discription_deb='摘要',
            account_cd_cre='41400', journal_amount_cre=Decimal('1100'),
            journal_discription_cre='貸方摘要',
        )
        defaults.update(extra)
        return T_DocumentContent.objects.create(**defaults)

    def test_complete_sets_journal_done_2_and_journal_at(self):
        """POST で対象明細が journal_done=2・journal_at セットになること"""
        doc = self._doc()
        c1 = self._content(doc)
        c2 = self._content(doc, date=datetime.date(2026, 7, 2))

        res = self.client.post(
            '/settings/settlement/journal/complete/',
            {'ids': f'{c1.pk},{c2.pk}'},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['updated'], 2)

        for c in (c1, c2):
            c.refresh_from_db()
            self.assertEqual(c.journal_done, 2)
            self.assertIsNotNone(c.journal_at)

    def test_complete_includes_split_rows(self):
        """元行のidのみ指定しても、その分割行も仕訳取込済みになること"""
        doc = self._doc()
        parent = self._content(doc)
        split = T_DocumentContent.all_objects.create(
            document=doc, split_from=parent, account=self.account,
            settle_kbn='CAS_INPRO', journal_done=1,
            journal_amont=Decimal('500'),
            journal_discription_deb='分割', date=datetime.date(2026, 7, 1),
        )

        res = self.client.post(
            '/settings/settlement/journal/complete/', {'ids': str(parent.pk)},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['updated'], 2)

        parent.refresh_from_db()
        split.refresh_from_db()
        self.assertEqual(parent.journal_done, 2)
        self.assertEqual(split.journal_done, 2)

    def test_completed_rows_excluded_from_csv_and_list(self):
        """journal_done=2 の行がCSV対象・出力一覧から外れること"""
        doc = self._doc()
        c1 = self._content(doc)

        self.client.post('/settings/settlement/journal/complete/', {'ids': str(c1.pk)})

        # CSV: データ行なし（ヘッダのみ）
        res = self.client.get(f'/settings/settlement/journal/csv/?ids={c1.pk}')
        text = b''.join(res.streaming_content).decode('utf-8-sig')
        rows = list(_csv.reader(StringIO(text)))
        self.assertEqual(len(rows), 1)

        # 出力一覧: 対象データなし表示（該当明細IDのチェックボックスがない）
        res = self.client.get('/settings/settlement/journal/')
        self.assertNotContains(res, f'value="{c1.pk}"')

    def test_debt_complete_only_targets_debt_kbn(self):
        """債務管理の完了APIは LON_INPRO のみ対象で、仕訳側(CAS_INPRO)の明細は更新しないこと"""
        doc = self._doc()
        cas = self._content(doc)                              # 仕訳側
        lon = self._content(doc, settle_kbn='LON_INPRO')      # 債務管理側

        res = self.client.post(
            '/settings/settlement/debt/complete/', {'ids': f'{cas.pk},{lon.pk}'},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['updated'], 1)

        cas.refresh_from_db()
        lon.refresh_from_db()
        self.assertEqual(cas.journal_done, 1)
        self.assertEqual(lon.journal_done, 2)

    def test_get_not_allowed_and_empty_ids_rejected(self):
        """GET は 405、ids 未指定は 400 になること"""
        res = self.client.get('/settings/settlement/journal/complete/')
        self.assertEqual(res.status_code, 405)

        res = self.client.post('/settings/settlement/journal/complete/', {'ids': ''})
        self.assertEqual(res.status_code, 400)
