"""債務管理CSV出力（debt_csv）が貸方を集約せず、
借方・貸方を明細行ごとにそのまま出力することのテスト。

仕訳CSV（journal_csv）は従来通り伝票単位で貸方を集約する（仕様が分かれる）。
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

# CSV列インデックス（views._journal_csv_view の COLUMNS 準拠）
IDX_DENPYO       = 0    # 伝票区切
IDX_DETAIL_ID    = 2    # 申請明細番号
IDX_AMOUNT_CRE   = 35   # 税抜金額(貸方)
IDX_DESC_CRE     = 42   # 摘要（貸方）


class DebtCsvPassthroughTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.status_fns, _ = M_Status.objects.get_or_create(
            status_cd='FNS', defaults={'status_name': '最終承認'}
        )
        grp, _ = M_DocumentGroup.objects.get_or_create(
            menu_group='LON',
            defaults={'menu_group_name': '前借証', 'category': 'expense', 'menu_order': 9},
        )
        cls.doc_type, _ = M_DocumentType.objects.get_or_create(
            document_type_id=11,
            defaults={'document_type_name': '前借証', 'menu_group': grp},
        )
        cls.account, _ = M_Account.objects.get_or_create(
            account_cd='13700', defaults={'account_name': '前払費用'}
        )
        cls.user, _ = User.objects.get_or_create(
            man_number='DCP001',
            defaults={'username': 'debt_csv_passthrough_user', 'user_name': '債務太郎'},
        )

    def setUp(self):
        self.client.force_login(self.user)

    def _content(self, doc, date_, **extra):
        defaults = dict(
            document=doc, date=date_, account=self.account,
            settle_kbn='LON_INPRO', journal_done=True,
            journal_amont=Decimal('1000'), journal_tax=Decimal('100'),
            journal_tax_kbn='312', journal_tax_rate='10%',
            journal_discription_deb='摘要',
            account_cd_cre='41400', journal_amount_cre=Decimal('1100'),
            journal_discription_cre='貸方摘要',
        )
        defaults.update(extra)
        return T_DocumentContent.objects.create(**defaults)

    def _csv_rows(self, url, ids):
        res = self.client.get(url + '?ids=' + ','.join(str(i) for i in ids))
        self.assertEqual(res.status_code, 200)
        text = b''.join(res.streaming_content).decode('utf-8-sig')
        rows = list(_csv.reader(StringIO(text)))[1:]  # ヘッダ行を除く
        return [[cell.lstrip(chr(0xFEFF)) for cell in row] for row in rows]

    def test_debt_csv_does_not_aggregate_credit_rows(self):
        """債務管理CSV: 同一伝票内で貸方キーが同じ明細でも合算されず、
        各行が自分の貸方値を保持したまま出力されること"""
        doc = T_Document.objects.create(
            document_type=self.doc_type, title='前借申請', man_number=self.user,
            status_cd=self.status_fns,
            settled_at=datetime.datetime(2026, 7, 10, 0, 0, 0),
        )
        c1 = self._content(doc, datetime.date(2026, 7, 1),
                           journal_amount_cre=Decimal('1100'),
                           journal_discription_cre='貸方摘要1')
        c2 = self._content(doc, datetime.date(2026, 7, 2),
                           journal_amount_cre=Decimal('2200'),
                           journal_discription_cre='貸方摘要2')

        rows = self._csv_rows('/settings/settlement/debt/csv/', [c1.pk, c2.pk])
        by_detail_id = {row[IDX_DETAIL_ID]: row for row in rows}

        self.assertEqual(len(rows), 2)
        # 各行が自分の貸方金額・摘要を保持している（合算・詰め直しされない）
        self.assertEqual(Decimal(by_detail_id[str(c1.pk)][IDX_AMOUNT_CRE]), Decimal('1100'))
        self.assertEqual(by_detail_id[str(c1.pk)][IDX_DESC_CRE], '貸方摘要1')
        self.assertEqual(Decimal(by_detail_id[str(c2.pk)][IDX_AMOUNT_CRE]), Decimal('2200'))
        self.assertEqual(by_detail_id[str(c2.pk)][IDX_DESC_CRE], '貸方摘要2')

    def test_debt_csv_denpyo_kubun_marks_first_row_of_voucher(self):
        """債務管理CSV: 伝票区切'*'は現行同様、伝票(settled_at+申請番号)の先頭行のみに付くこと"""
        doc_a = T_Document.objects.create(
            document_type=self.doc_type, title='前借A', man_number=self.user,
            status_cd=self.status_fns,
            settled_at=datetime.datetime(2026, 7, 10, 0, 0, 0),
        )
        a1 = self._content(doc_a, datetime.date(2026, 7, 1))
        a2 = self._content(doc_a, datetime.date(2026, 7, 2))
        doc_b = T_Document.objects.create(
            document_type=self.doc_type, title='前借B', man_number=self.user,
            status_cd=self.status_fns,
            settled_at=datetime.datetime(2026, 7, 11, 0, 0, 0),
        )
        b1 = self._content(doc_b, datetime.date(2026, 7, 3))

        rows = self._csv_rows('/settings/settlement/debt/csv/', [a1.pk, a2.pk, b1.pk])
        by_detail_id = {row[IDX_DETAIL_ID]: row for row in rows}

        self.assertEqual(by_detail_id[str(a1.pk)][IDX_DENPYO], '*')
        self.assertEqual(by_detail_id[str(a2.pk)][IDX_DENPYO], '')
        self.assertEqual(by_detail_id[str(b1.pk)][IDX_DENPYO], '*')

    def test_journal_csv_still_aggregates(self):
        """仕訳CSV: 従来通り貸方が集約される（債務管理と仕様が分かれる）こと"""
        doc = T_Document.objects.create(
            document_type=self.doc_type, title='仕訳申請', man_number=self.user,
            status_cd=self.status_fns,
            settled_at=datetime.datetime(2026, 7, 12, 0, 0, 0),
        )
        c1 = self._content(doc, datetime.date(2026, 7, 1),
                           settle_kbn='CAS_INPRO',
                           journal_amount_cre=Decimal('1100'))
        c2 = self._content(doc, datetime.date(2026, 7, 2),
                           settle_kbn='CAS_INPRO',
                           journal_amount_cre=Decimal('2200'))

        rows = self._csv_rows('/settings/settlement/journal/csv/', [c1.pk, c2.pk])
        by_detail_id = {row[IDX_DETAIL_ID]: row for row in rows}

        # 貸方キーが同じ2行は合算され、伝票先頭行に 3300、2行目は空になる
        self.assertEqual(Decimal(by_detail_id[str(c1.pk)][IDX_AMOUNT_CRE]), Decimal('3300'))
        self.assertEqual(by_detail_id[str(c2.pk)][IDX_AMOUNT_CRE], '')
