"""グループ/ユーザーマネージャー画面のテスト"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from expenses.models import M_BelongTo, M_Bumon, M_Group, M_Post

User = get_user_model()


class BuildGroupTreeTests(TestCase):
    """build_group_tree 純粋関数のテスト"""

    def test_通常階層はDFS順で同階層はコード昇順(self):
        from expenses.views_org_manager import build_group_tree
        M_Group.objects.create(group_cd='200', group_name='営業本部', upper_group_cd='')
        M_Group.objects.create(group_cd='100', group_name='管理本部', upper_group_cd='')
        M_Group.objects.create(group_cd='110', group_name='経理部', upper_group_cd='100')
        M_Group.objects.create(group_cd='111', group_name='経理課', upper_group_cd='110')
        nodes = build_group_tree(list(M_Group.objects.all()))
        result = [(n['group'].group_cd, n['depth']) for n in nodes]
        self.assertEqual(
            result, [('100', 0), ('110', 1), ('111', 2), ('200', 0)])
        self.assertEqual(nodes[1]['indent'], 18)
        self.assertFalse(any(n['is_orphan'] for n in nodes))

    def test_上位コードが存在しない部署はorphanのルート扱い(self):
        from expenses.views_org_manager import build_group_tree
        M_Group.objects.create(group_cd='300', group_name='孤児部署', upper_group_cd='999')
        nodes = build_group_tree(list(M_Group.objects.all()))
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]['depth'], 0)
        self.assertTrue(nodes[0]['is_orphan'])

    def test_循環参照でも無限ループせず全件出る(self):
        from expenses.views_org_manager import build_group_tree
        M_Group.objects.create(group_cd='A', group_name='A部', upper_group_cd='B')
        M_Group.objects.create(group_cd='B', group_name='B部', upper_group_cd='A')
        nodes = build_group_tree(list(M_Group.objects.all()))
        self.assertEqual(len(nodes), 2)
        self.assertTrue(all(n['is_orphan'] for n in nodes))

    def test_upper_group_cdがNoneでもルート扱い(self):
        from expenses.views_org_manager import build_group_tree
        M_Group.objects.create(group_cd='100', group_name='本社', upper_group_cd=None)
        nodes = build_group_tree(list(M_Group.objects.all()))
        self.assertEqual(nodes[0]['depth'], 0)
        self.assertFalse(nodes[0]['is_orphan'])

    def test_循環ノードは全てルート扱いで循環外の子は下にネストされる(self):
        from expenses.views_org_manager import build_group_tree
        M_Group.objects.create(group_cd='A', group_name='A部', upper_group_cd='B')
        M_Group.objects.create(group_cd='B', group_name='B部', upper_group_cd='A')
        M_Group.objects.create(group_cd='D', group_name='D課', upper_group_cd='A')
        nodes = build_group_tree(list(M_Group.objects.all()))
        result = [(n['group'].group_cd, n['depth'], n['is_orphan']) for n in nodes]
        self.assertEqual(result, [
            ('A', 0, True), ('D', 1, False), ('B', 0, True)])

    def test_orphan配下の通常ノードはorphan扱いにならない(self):
        from expenses.views_org_manager import build_group_tree
        M_Group.objects.create(group_cd='O', group_name='孤児部', upper_group_cd='999')
        M_Group.objects.create(group_cd='C', group_name='子課', upper_group_cd='O')
        nodes = build_group_tree(list(M_Group.objects.all()))
        result = [(n['group'].group_cd, n['depth'], n['is_orphan']) for n in nodes]
        self.assertEqual(result, [('O', 0, True), ('C', 1, False)])


class GroupManagerListViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.login_user = User.objects.create_user(
            username='tester', man_number='9001',
            user_name='テスト太郎', password='pass')
        root = M_Group.objects.create(
            group_cd='100', group_name='管理本部', upper_group_cd='')
        child = M_Group.objects.create(
            group_cd='110', group_name='経理部', upper_group_cd='100')
        member = User.objects.create_user(
            username='member1', man_number='9002',
            user_name='所属花子', password='pass')
        M_BelongTo.objects.create(man_number=member, group_cd=child)

    def test_m_groupの一覧はツリー画面が返る(self):
        self.client.force_login(self.login_user)
        res = self.client.get(
            reverse('expenses:settings_master_list', args=['m_group']))
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'expenses/group_manager_list.html')
        self.assertContains(res, '経理部')
        self.assertContains(res, '所属花子')  # 展開用に埋め込まれる所属ユーザー名

    def test_他のマスタキーは従来の汎用画面のまま(self):
        self.client.force_login(self.login_user)
        res = self.client.get(
            reverse('expenses:settings_master_list', args=['m_bumon']))
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'expenses/settings_master_list.html')


class MasterCreateInitialTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.login_user = User.objects.create_user(
            username='tester2', man_number='9003',
            user_name='テスト次郎', password='pass')

    def test_GETパラメータがフォーム初期値に入る(self):
        self.client.force_login(self.login_user)
        res = self.client.get(
            reverse('expenses:settings_master_create', args=['m_group'])
            + '?upper_group_cd=100')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            res.context['form'].initial.get('upper_group_cd'), '100')

    def test_フォームに存在しないGETパラメータは無視される(self):
        self.client.force_login(self.login_user)
        res = self.client.get(
            reverse('expenses:settings_master_create', args=['m_group'])
            + '?evil_param=x')
        self.assertEqual(res.status_code, 200)
        self.assertNotIn('evil_param', res.context['form'].initial)


class UserManagerListViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.login_user = User.objects.create_user(
            username='tester3', man_number='9004',
            user_name='テスト三郎', password='pass')
        cls.bumon = M_Bumon.objects.create(bumon_cd='B01', bumon_name='管理部門')
        cls.post = M_Post.objects.create(post_cd='P01', post_name='課長', post_order=10)
        cls.group = M_Group.objects.create(
            group_cd='110', group_name='経理部', upper_group_cd='')
        cls.active_user = User.objects.create_user(
            username='u_active', man_number='1001', user_name='有効太郎',
            password='pass', bumon_cd=cls.bumon, post_cd=cls.post, is_active=True)
        cls.inactive_user = User.objects.create_user(
            username='u_inactive', man_number='1002', user_name='無効花子',
            password='pass', is_active=False)
        M_BelongTo.objects.create(man_number=cls.active_user, group_cd=cls.group)

    def _get(self, params=''):
        self.client.force_login(self.login_user)
        url = reverse('expenses:settings_master_list', args=['m_user'])
        return self.client.get(url + params)

    def test_m_userの一覧は専用画面でデフォルト有効のみ表示(self):
        res = self._get()
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'expenses/user_manager_list.html')
        self.assertContains(res, '有効太郎')
        self.assertNotContains(res, '無効花子')

    def test_statusフィルタallで無効ユーザーも表示(self):
        res = self._get('?status=all')
        self.assertContains(res, '有効太郎')
        self.assertContains(res, '無効花子')

    def test_所属部署フィルタ(self):
        res = self._get('?group=110')
        self.assertContains(res, '有効太郎')
        # ログインユーザー自身の氏名はナビゲーションバーに常時表示されるため、
        # HTML全体でのassertNotContainsは使えない。一覧結果（page_obj）を検証する。
        man_numbers = [u.man_number for u in res.context['page_obj']]
        self.assertNotIn(self.login_user.man_number, man_numbers)  # 未所属のログインユーザーは出ない

    def test_キーワード検索は社員番号と氏名を対象(self):
        res = self._get('?q=1001')
        self.assertContains(res, '有効太郎')
        res = self._get('?q=太郎')
        self.assertContains(res, '有効太郎')

    def test_所属部署列と未所属表示(self):
        res = self._get('?status=all')
        self.assertContains(res, '経理部')      # active_user の所属部署
        self.assertContains(res, '（未所属）')  # inactive_user は未所属


class UserToggleActiveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.login_user = User.objects.create_user(
            username='tester4', man_number='9005',
            user_name='テスト四郎', password='pass')
        cls.target = User.objects.create_user(
            username='target1', man_number='1003',
            user_name='対象五郎', password='pass', is_active=True)

    def _url(self, pk):
        return reverse('expenses:user_toggle_active', args=[pk])

    def test_POSTで有効無効がトグルしJSONが返る(self):
        self.client.force_login(self.login_user)
        res = self.client.post(self._url(self.target.pk))
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()['is_active'])
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)
        # もう一度で戻る
        res = self.client.post(self._url(self.target.pk))
        self.assertTrue(res.json()['is_active'])

    def test_自分自身は無効化できない(self):
        self.client.force_login(self.login_user)
        res = self.client.post(self._url(self.login_user.pk))
        self.assertEqual(res.status_code, 400)
        self.login_user.refresh_from_db()
        self.assertTrue(self.login_user.is_active)

    def test_GETは405(self):
        self.client.force_login(self.login_user)
        res = self.client.get(self._url(self.target.pk))
        self.assertEqual(res.status_code, 405)
