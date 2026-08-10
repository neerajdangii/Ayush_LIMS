from django.core.exceptions import ValidationError


class MaximumPasswordLengthValidator:
    """Keep credentials within the organisation's 16-character policy."""

    max_length = 16

    def validate(self, password, user=None):
        if len(password) > self.max_length:
            raise ValidationError(
                f"Password must contain at most {self.max_length} characters.",
                code="password_too_long",
            )

    def get_help_text(self):
        return f"Your password must contain at most {self.max_length} characters."
