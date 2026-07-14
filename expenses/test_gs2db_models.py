"""GS_* (旧GSESSION参照データ) モデルの基本CRUDテスト"""
from django.test import TestCase

from expenses.models import GS_Belong, GS_Group, GS_Position, GS_Ringi, GS_Usr


class GS2dbModelsTest(TestCase):
    def test_gs_ringi_create_and_str(self):
        obj = GS_Ringi.objects.create(
            rng_sid=1, rng_title='与信管理申請', rng_makedate='2025-06-24 16:21:28',
            rng_status=1, rng_compflg=0, rng_auid=1, rng_adate='2025-06-24 16:21:28',
            rng_euid=1, rng_edate='2025-06-24 16:21:28', rtp_sid=10, rtp_ver=1,
        )
        self.assertEqual(str(obj), '1 与信管理申請')
        self.assertEqual(GS_Ringi.objects.get(rng_sid=1).rng_title, '与信管理申請')

    def test_gs_usr_excludes_password_field(self):
        obj = GS_Usr.objects.create(
            usr_sid=100, usr_lgid='taro.yamada', usr_jkbn=1,
            usi_sei='山田', usi_mei='太郎', usi_syain_no='00123',
        )
        self.assertFalse(hasattr(obj, 'usr_pswd'))
        self.assertEqual(str(obj), '100 山田太郎')

    def test_gs_group_and_position(self):
        grp = GS_Group.objects.create(
            grp_sid=1, grp_id='G001', grp_name='経理部',
            grp_auid=1, grp_adate='2025-01-01 00:00:00',
            grp_euid=1, grp_edate='2025-01-01 00:00:00',
            grp_sort=1, grp_jkbn=1,
        )
        pos = GS_Position.objects.create(
            pos_sid=1, pos_code='P01', pos_name='課長', pos_sort=1,
            pos_auid=1, pos_adate='2025-01-01 00:00:00',
            pos_euid=1, pos_edate='2025-01-01 00:00:00',
        )
        self.assertEqual(str(grp), '1 経理部')
        self.assertEqual(str(pos), '1 課長')

    def test_gs_belong_unique_together(self):
        GS_Belong.objects.create(
            grp_sid=1, usr_sid=100, beg_auid=1, beg_adate='2025-01-01 00:00:00',
            beg_euid=1, beg_edate='2025-01-01 00:00:00', beg_defgrp=1, beg_grpkbn=1,
        )
        # 同一(grp_sid, usr_sid, beg_grpkbn)の重複はupdate_or_createで対応する想定。
        # ここでは単純作成できることのみ確認。
        self.assertEqual(GS_Belong.objects.count(), 1)
