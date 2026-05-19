from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0045_fix_feedback_collation'),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE t_feedback CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
