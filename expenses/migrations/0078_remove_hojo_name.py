from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0077_journal_fields'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='t_documentcontent',
            name='hojo_name',
        ),
    ]
