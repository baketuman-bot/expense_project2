from django.contrib.auth.backends import ModelBackend
from .models import M_User


class ManNumberModelBackend(ModelBackend):
    """
    Authenticate using M_User.man_number as the identifier.
    Falls back to username match to preserve compatibility if desired.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        # Accept either explicit man_number or the provided username field as man_number
        identifier = kwargs.get("man_number") or username
        if identifier is None or password is None:
            return None

        user = None
        # Try man_number first
        try:
            user = M_User.objects.get(man_number=identifier)
        except M_User.DoesNotExist:
            # Optional fallback: allow username-based login too
            try:
                user = M_User.objects.get(username=identifier)
            except M_User.DoesNotExist:
                return None

        if user and user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
