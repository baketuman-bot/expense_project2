"""中国輸出実績報告 (T_ChinaExport) のテスト"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from expenses.models import M_UserRole, T_ChinaExport

User = get_user_model()


class TChinaExportModelTests(TestCase):
    def test_品目名1がNullだと保存時にエラー(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                T_ChinaExport.objects.create(item_name1=None, amount=Decimal('100.00'))

    def test_金額がNullだと保存時にエラー(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                T_ChinaExport.objects.create(item_name1='テスト品目', amount=None)

    def test_品目名1と金額以外はNullで保存できる(self):
        record = T_ChinaExport.objects.create(
            item_name1='テスト品目', amount=Decimal('1000.00'))
        self.assertIsNone(record.order_no)
        self.assertIsNone(record.purchase_date)
        self.assertIsNone(record.export_planned_date)
        self.assertIsNone(record.export_date)
        self.assertIsNone(record.invoice_no)
        self.assertIsNone(record.updated_by)


class ChinaExportListViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.export_user = User.objects.create_user(
            username='export_tester', man_number='9101',
            user_name='輸出担当', password='pass')
        M_UserRole.objects.create(man_number=cls.export_user, role='export')

        cls.other_user = User.objects.create_user(
            username='other_tester', man_number='9102',
            user_name='権限なし', password='pass')

        cls.admin_user = User.objects.create_user(
            username='admin_tester', man_number='9107',
            user_name='管理者', password='pass')
        M_UserRole.objects.create(man_number=cls.admin_user, role='admin')

        cls.unexported = T_ChinaExport.objects.create(
            item_name1='未輸出品', amount=Decimal('5000.00'),
            purchase_date=date(2026, 6, 1),
            supplier_name='上海サプライヤー', order_staff_name='山田太郎',
            account_name='仕入高', burden_bumon_name='営業部')
        cls.exported = T_ChinaExport.objects.create(
            item_name1='輸出済品', amount=Decimal('3000.00'),
            purchase_date=date(2026, 5, 1),
            export_date=date(2026, 6, 15))

    def test_exportロールを持たないユーザーは403(self):
        self.client.force_login(self.other_user)
        res = self.client.get(reverse('expenses:china_export_list'))
        self.assertEqual(res.status_code, 403)

    def test_adminロールを持っていてもexportロールがなければ403(self):
        # 設計上の制約: exportロールのみ許可、管理者バイパスなし
        self.client.force_login(self.admin_user)
        res = self.client.get(reverse('expenses:china_export_list'))
        self.assertEqual(res.status_code, 403)

    def test_経理入力項目がテンプレートに表示される(self):
        self.client.force_login(self.export_user)
        res = self.client.get(reverse('expenses:china_export_list'))
        self.assertContains(res, '上海サプライヤー')
        self.assertContains(res, '山田太郎')
        self.assertContains(res, '仕入高')
        self.assertContains(res, '営業部')

    def test_デフォルトは未輸出のみ表示(self):
        self.client.force_login(self.export_user)
        res = self.client.get(reverse('expenses:china_export_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, '未輸出品')
        self.assertNotContains(res, '輸出済品')

    def test_show_allで全件表示(self):
        self.client.force_login(self.export_user)
        res = self.client.get(reverse('expenses:china_export_list') + '?show=all')
        self.assertContains(res, '未輸出品')
        self.assertContains(res, '輸出済品')

    def test_購入日昇順で並ぶ(self):
        self.client.force_login(self.export_user)
        res = self.client.get(reverse('expenses:china_export_list') + '?show=all')
        records = list(res.context['records'])
        self.assertEqual(
            [r.pk for r in records],
            [self.exported.pk, self.unexported.pk])


class ChinaExportUpdateViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.export_user = User.objects.create_user(
            username='export_tester2', man_number='9103',
            user_name='輸出担当2', password='pass')
        M_UserRole.objects.create(man_number=cls.export_user, role='export')
        cls.other_user = User.objects.create_user(
            username='other_tester2', man_number='9104',
            user_name='権限なし2', password='pass')
        cls.admin_user = User.objects.create_user(
            username='admin_tester2', man_number='9108',
            user_name='管理者2', password='pass')
        M_UserRole.objects.create(man_number=cls.admin_user, role='admin')
        cls.record = T_ChinaExport.objects.create(
            order_no='ORDER0001', item_name1='対象品目', amount=Decimal('1234.00'))

    def test_exportロールを持たないユーザーは更新不可(self):
        self.client.force_login(self.other_user)
        res = self.client.post(
            reverse('expenses:china_export_update', args=[self.record.pk]),
            {'export_planned_date': '2026-08-01', 'export_date': '', 'invoice_no': 'INV-001'})
        self.assertEqual(res.status_code, 403)

    def test_adminロールを持っていてもexportロールがなければ更新不可(self):
        # 設計上の制約: exportロールのみ許可、管理者バイパスなし
        self.client.force_login(self.admin_user)
        res = self.client.post(
            reverse('expenses:china_export_update', args=[self.record.pk]),
            {'export_planned_date': '2026-08-01', 'export_date': '', 'invoice_no': 'INV-001'})
        self.assertEqual(res.status_code, 403)
        self.record.refresh_from_db()
        self.assertIsNone(self.record.export_planned_date)

    def test_輸出予定日と輸出日とインボイスNoが保存されupdated_byが記録される(self):
        original_updated_at = self.record.updated_at
        self.client.force_login(self.export_user)
        res = self.client.post(
            reverse('expenses:china_export_update', args=[self.record.pk]),
            {'export_planned_date': '2026-08-01', 'export_date': '2026-08-10', 'invoice_no': 'INV-001'})
        self.assertRedirects(res, reverse('expenses:china_export_list'))
        self.record.refresh_from_db()
        self.assertEqual(self.record.export_planned_date, date(2026, 8, 1))
        self.assertEqual(self.record.export_date, date(2026, 8, 10))
        self.assertEqual(self.record.invoice_no, 'INV-001')
        self.assertEqual(self.record.updated_by, self.export_user)
        self.assertIsNotNone(self.record.updated_at)
        self.assertNotEqual(self.record.updated_at, original_updated_at)

    def test_経理入力項目はPOSTに含めても更新されない(self):
        self.client.force_login(self.export_user)
        self.client.post(
            reverse('expenses:china_export_update', args=[self.record.pk]),
            {
                'export_planned_date': '', 'export_date': '', 'invoice_no': '',
                'order_no': 'HACKED', 'amount': '999999.00',
            })
        self.record.refresh_from_db()
        self.assertEqual(self.record.order_no, 'ORDER0001')
        self.assertEqual(self.record.amount, Decimal('1234.00'))

    def test_show_allを維持したままリダイレクトされる(self):
        self.client.force_login(self.export_user)
        res = self.client.post(
            reverse('expenses:china_export_update', args=[self.record.pk]),
            {'export_planned_date': '', 'export_date': '', 'invoice_no': '', 'show': 'all'})
        self.assertRedirects(res, reverse('expenses:china_export_list') + '?show=all')


class ChinaExportSidebarTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.export_user = User.objects.create_user(
            username='export_tester3', man_number='9105',
            user_name='輸出担当3', password='pass')
        M_UserRole.objects.create(man_number=cls.export_user, role='export')
        cls.other_user = User.objects.create_user(
            username='other_tester3', man_number='9106',
            user_name='権限なし3', password='pass')

    def test_exportロール保持者はサイドバーにメニューが出る(self):
        self.client.force_login(self.export_user)
        res = self.client.get(reverse('expenses:home'))
        self.assertContains(res, '中国輸出実績報告')

    def test_exportロールがないユーザーには出ない(self):
        self.client.force_login(self.other_user)
        res = self.client.get(reverse('expenses:home'))
        self.assertNotContains(res, '中国輸出実績報告')
