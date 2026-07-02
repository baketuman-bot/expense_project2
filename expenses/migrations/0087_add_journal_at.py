from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0086_add_mysql_comments_journal_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='t_documentcontent',
            name='journal_at',
            field=models.DateField(blank=True, null=True, verbose_name='仕訳処理日'),
        ),
    ]
