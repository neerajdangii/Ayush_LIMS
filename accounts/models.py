from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .sanitizers import sanitize_announcement_html


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


class WelcomeAnnouncement(models.Model):
    """Reusable, dashboard-delivered announcement (welcome, maintenance, news, etc.)."""

    class AnnouncementType(models.TextChoices):
        WELCOME = "welcome", "Welcome"
        FEATURE = "feature", "New feature"
        MAINTENANCE = "maintenance", "Maintenance notice"
        HOLIDAY = "holiday", "Holiday greeting"
        NEWS = "news", "Company news"
        ALERT = "alert", "Emergency alert"
        RELEASE = "release", "Release notes / version update"
        TRAINING = "training", "Training announcement"

    class ButtonAction(models.TextChoices):
        CLOSE = "close", "Close popup"
        URL = "url", "Open a URL"
        INTERNAL = "internal", "Open an internal page"

    class DisplayMode(models.TextChoices):
        ONCE = "once", "Only once per user"
        DAILY = "daily", "Once per day for each user"
        LOGIN = "login", "Every login (do not show again on page refresh)"

    announcement_type = models.CharField(max_length=60, default="Welcome")
    title = models.CharField(max_length=180)
    message = models.TextField(blank=True)
    image = models.ImageField(upload_to="announcements/", blank=True, null=True)
    button_text = models.CharField(max_length=60, blank=True, default="Get Started")
    button_action = models.CharField(max_length=20, choices=ButtonAction.choices, default=ButtonAction.INTERNAL)
    button_url = models.CharField(max_length=500, blank=True, default="/")
    is_active = models.BooleanField(default=False)
    display_mode = models.CharField(max_length=20, choices=DisplayMode.choices, default=DisplayMode.LOGIN)
    presentation = models.CharField(max_length=12, choices=[("popup", "Popup"), ("page", "Full page")], default="popup")
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)
    allow_close = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="created_announcements")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_active", "-updated_at"]
        permissions = [("manage_welcome_announcement", "Can manage Welcome Announcement")]

    def clean(self):
        self.message = sanitize_announcement_html(self.message)
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "End date must be on or after the start date."})
        if self.button_action in {self.ButtonAction.URL, self.ButtonAction.INTERNAL} and not self.button_url.strip():
            raise ValidationError({"button_url": "Enter a destination for this button action."})

    @property
    def is_current(self):
        today = timezone.localdate()
        return self.is_active and (not self.start_date or self.start_date <= today) and (not self.end_date or today <= self.end_date)

    def __str__(self):
        return self.title


class AnnouncementSeen(models.Model):
    announcement = models.ForeignKey(WelcomeAnnouncement, on_delete=models.CASCADE, related_name="seen_records")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="announcement_views")
    session_key = models.CharField(max_length=64, blank=True)
    seen_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["announcement", "user"]), models.Index(fields=["announcement", "session_key"])]


class SystemSetting(models.Model):
    """Singleton-style settings that control login access and idle sessions."""

    class CertificateNumberingMode(models.TextChoices):
        CONTINUOUS = "continuous", "Continuous serial (0001... )"
        DAILY = "daily", "Daily serial by receipt date (001... )"

    login_enabled = models.BooleanField(default=True)
    session_timeout_minutes = models.PositiveIntegerField(default=0, help_text="Use 0 to disable automatic logout.")
    certificate_numbering_mode = models.CharField(
        max_length=16,
        choices=CertificateNumberingMode.choices,
        default=CertificateNumberingMode.DAILY,
        help_text="Select how booking certificate numbers are generated for reports.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        permissions = [
            ("manage_system_settings", "Can manage system settings"),
            ("edit_tinymce_source", "Can edit TinyMCE source code"),
            ("manage_users", "Can create and manage limited users"),
        ]

    @classmethod
    def current(cls):
        setting, _ = cls.objects.get_or_create(pk=1)
        return setting
