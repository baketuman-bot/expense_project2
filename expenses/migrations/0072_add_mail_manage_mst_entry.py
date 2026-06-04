from django.db import migrations


def add_mail_manage_mst(apps, schema_editor):
    M_Item = apps.get_model('expenses', 'M_Item')
    # m_mail_manage エントリを追加
    M_Item.objects.get_or_create(
        data_kbn='MST',
        content='m_mail_manage',
        defaults={'key': '16', 'content2': 'メール送信管理'},
    )
    # typo 修正: m_document_type の content2
    M_Item.objects.filter(data_kbn='MST', content='m_document_type').update(content2='申請書タイプ')
    # typo 修正: m_group の content2
    M_Item.objects.filter(data_kbn='MST', content='m_group').update(content2='部門グループ')


def remove_mail_manage_mst(apps, schema_editor):
    M_Item = apps.get_model('expenses', 'M_Item')
    M_Item.objects.filter(data_kbn='MST', content='m_mail_manage').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0071_remove_user_groups_permissions'),
    ]

    operations = [
        migrations.RunPython(add_mail_manage_mst, remove_mail_manage_mst),
    ]
