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
