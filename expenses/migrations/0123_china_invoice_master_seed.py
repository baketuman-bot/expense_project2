from django.db import migrations


def seed_master_data(apps, schema_editor):
    M_Item = apps.get_model('expenses', 'M_Item')
    cargo_rows = [
        ('1', '製品', ''),
        ('2', '資材', ''),
        ('3', '部品', ''),
        ('4', '金型', ''),
        ('5', '設備', ''),
        ('6', 'その他', 'OTHER'),
    ]
    for order, (key, content, content2) in enumerate(cargo_rows, start=1):
        M_Item.objects.get_or_create(
            data_kbn='CHN_CARGO', key=key,
            defaults={'content': content, 'content2': content2, 'order_by': order},
        )

    adjrate_rows = [
        ('1', '0%', '0.00'),
        ('2', '1%', '1.00'),
        ('3', '5%', '5.00'),
    ]
    for order, (key, content, content2) in enumerate(adjrate_rows, start=1):
        M_Item.objects.get_or_create(
            data_kbn='CHN_ADJRATE', key=key,
            defaults={'content': content, 'content2': content2, 'order_by': order},
        )


def remove_master_data(apps, schema_editor):
    M_Item = apps.get_model('expenses', 'M_Item')
    M_Item.objects.filter(data_kbn__in=['CHN_CARGO', 'CHN_ADJRATE']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0122_alter_m_item_data_kbn'),
    ]

    operations = [
        migrations.RunPython(seed_master_data, remove_master_data),
    ]
