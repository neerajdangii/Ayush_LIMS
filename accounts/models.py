from __future__ import annotations

from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    signature_file = models.FileField(upload_to="signatures/", blank=True, null=True)

    def __str__(self) -> str:
        return f"Profile: {self.user.username}"


class UserActivity(models.Model):
    """An audit record for an authenticated request made in the application."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="activities",
        null=True,
        blank=True,
    )
    activity = models.CharField(max_length=255)
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=500)
    status_code = models.PositiveSmallIntegerField()
    browser = models.CharField(max_length=100, blank=True)
    device = models.CharField(max_length=50, blank=True)
    user_agent = models.CharField(max_length=1000, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = [
            ("view_user_activity", "Can view User Activity"),
        ]
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["user", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.user or 'Deleted user'}: {self.activity}"
