"""仕訳CSV出力の伝票区切（denpyo_kubun）が
t_documents.settled_at + document_id でグルーピングされることのテスト"""
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


class JournalCsvSettledAtGroupingTest(TestCase):
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
            man_number='JCG001',
            defaults={'username': 'journal_csv_grouping_user', 'user_name': '集計太郎'},
        )

    def setUp(self):
        self.client.force_login(self.user)

    def _content(self, doc, date_, **extra):
        defaults = dict(
            document=doc, date=date_, account=self.account,
            settle_kbn='CAS_INPRO', journal_done=True,
            journal_amont=Decimal('1000'), journal_tax=Decimal('100'),
            journal_tax_kbn='312', journal_tax_rate='10%',
            journal_discription_deb='摘要',
            account_cd_cre='41400', journal_amount_cre=Decimal('1100'),
            journal_discription_cre='貸方摘要',
        )
        defaults.update(extra)
        return T_DocumentContent.objects.create(**defaults)

    def _csv_rows(self, ids):
        """CSVの行データを返す（ヘッダ行を除く）。

        既存の実装は StreamingHttpResponse が行ごとに個別の文字列チャンクを
        yield し、charset=utf-8-sig の指定により各チャンクが個別にBOM付きで
        エンコードされる（str.encode('utf-8-sig')は呼び出しごとに先頭へBOMを
        付与するため）。そのため実際のCSVファイルは全行の先頭列に不可視の
        BOM文字が混入している（本テストのスコープ外の既存不具合）。
        ここでは各セルの先頭BOMを取り除いてから比較する。
        """
        res = self.client.get(
            '/settings/settlement/journal/csv/?ids=' + ','.join(str(i) for i in ids))
        self.assertEqual(res.status_code, 200)
        text = b''.join(res.streaming_content).decode('utf-8-sig')
        rows = list(_csv.reader(StringIO(text)))[1:]  # ヘッダ行を除く
        return [[cell.lstrip(chr(0xFEFF)) for cell in row] for row in rows]

    def test_single_document_with_settled_at_null_and_varying_line_dates_stays_one_voucher(self):
        """settled_atが未設定（NULL）の申請で、明細の日付(content.date)が行ごとに異なっていても
        1つの伝票としてまとまる（間に別申請の行が挟まっても分断されない）こと"""
        doc_a = T_Document.objects.create(
            document_type=self.doc_type, title='申請A(settled_at未設定)', man_number=self.user,
            status_cd=self.status_fns, settled_at=None,
        )
        a1 = self._content(doc_a, datetime.date(2026, 7, 1))
        a2 = self._content(doc_a, datetime.date(2026, 7, 5))

        doc_b = T_Document.objects.create(
            document_type=self.doc_type, title='申請B', man_number=self.user,
            status_cd=self.status_fns,
            settled_at=datetime.datetime(2026, 7, 3, 0, 0, 0),
        )
        b1 = self._content(doc_b, datetime.date(2026, 7, 3))

        rows = self._csv_rows([a1.pk, a2.pk, b1.pk])
        by_detail_id = {row[2]: row for row in rows}

        # 申請Aの2明細が1つの伝票としてまとまり、'*'は先頭行のみに付くこと
        self.assertEqual(by_detail_id[str(a1.pk)][0], '*')
        self.assertEqual(by_detail_id[str(a2.pk)][0], '')
        # 申請Bは別伝票として '*' が付くこと
        self.assertEqual(by_detail_id[str(b1.pk)][0], '*')

    def test_same_settled_at_different_documents_each_marked(self):
        """同じ伝票日付(settled_at)でも申請番号が異なれば別伝票として区切られること"""
        same_settled = datetime.datetime(2026, 7, 10, 0, 0, 0)
        doc_a = T_Document.objects.create(
            document_type=self.doc_type, title='申請A', man_number=self.user,
            status_cd=self.status_fns, settled_at=same_settled,
        )
        doc_b = T_Document.objects.create(
            document_type=self.doc_type, title='申請B', man_number=self.user,
            status_cd=self.status_fns, settled_at=same_settled,
        )
        a1 = self._content(doc_a, datetime.date(2026, 7, 1))
        b1 = self._content(doc_b, datetime.date(2026, 7, 1))

        rows = self._csv_rows([a1.pk, b1.pk])
        markers = [row[0] for row in rows]
        self.assertEqual(markers, ['*', '*'])

    def test_settled_at_column_not_shown_as_csv_data(self):
        """集約キー専用のsettled_at列がCSVの見た目の列数に影響しない（ヘッダと行の列数が一致する）"""
        doc = T_Document.objects.create(
            document_type=self.doc_type, title='申請C', man_number=self.user,
            status_cd=self.status_fns,
            settled_at=datetime.datetime(2026, 7, 15, 0, 0, 0),
        )
        c1 = self._content(doc, datetime.date(2026, 7, 15))

        res = self.client.get(f'/settings/settlement/journal/csv/?ids={c1.pk}')
        text = b''.join(res.streaming_content).decode('utf-8-sig')
        rows = list(_csv.reader(StringIO(text)))
        header_len = len(rows[0])
        self.assertEqual(header_len, 38)
        self.assertEqual(len(rows[1]), header_len)
