from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0075_add_fields_to_item_and_bumon'),
    ]

    operations = [
        migrations.AlterField(
            model_name='m_workflowstep',
            name='allowed_bumon_scope',
            field=models.CharField(
                choices=[
                    ('same', '同一'),
                    ('parent', '親'),
                    ('keiri', '経理'),
                    ('assets', '固定資産'),
                    ('any', '全体'),
                ],
                default='any',
                max_length=7,
                verbose_name='部門許可範囲',
            ),
        ),
    ]
