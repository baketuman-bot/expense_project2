from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0044_add_feedback'),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE t_feedback CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
