from django.core.management.base import BaseCommand
from django.contrib.auth.models import get_user_model
from django.conf import settings

user = get_user_model()

class Command(BaseCommand):
    def handle(self, *args, **options):
        if not user.objects.filter(username='idc_user').exists():
            user.objects.create_superuser(
                username='idc_user',
                password='123',
                email=''
            )
            