from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from .forms import LoginForm
from .models import UserProfile
from .password_validators import MaximumPasswordLengthValidator


class LoginLockoutTests(TestCase):
    def test_third_wrong_password_deactivates_the_account(self):
        user = get_user_model().objects.create_user(username="locked-user", password="valid-password")

        for _ in range(3):
            form = LoginForm(data={"username": user.username, "password": "wrong-password"})
            self.assertFalse(form.is_valid())

        user.refresh_from_db()
        profile = UserProfile.objects.get(user=user)
        self.assertFalse(user.is_active)
        self.assertEqual(profile.failed_login_attempts, 3)

    def test_password_length_policy_rejects_more_than_sixteen_characters(self):
        with self.assertRaisesMessage(ValidationError, "at most 16 characters"):
            MaximumPasswordLengthValidator().validate("a" * 17)
