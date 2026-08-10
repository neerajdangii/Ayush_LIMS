from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import Group, Permission, User
from django.db import transaction
from django.utils import timezone

from .models import SystemSetting, UserProfile, WelcomeAnnouncement


MASTER_ACCESS_OPTIONS = [
    ("customer", "Customer Master", ["add_customermaster", "change_customermaster", "delete_customermaster", "view_customermaster"]),
    ("submitter", "Submitter Master", ["add_submittermaster", "change_submittermaster", "delete_submittermaster", "view_submittermaster"]),
    ("manufacturer", "Manufacturer Master", ["add_manufacturermaster", "change_manufacturermaster", "delete_manufacturermaster", "view_manufacturermaster"]),
    ("sample_name", "Sample Name Master", ["add_samplenamemaster", "change_samplenamemaster", "delete_samplenamemaster", "view_samplenamemaster"]),
    ("test", "Test Master", ["add_testmaster", "change_testmaster", "delete_testmaster", "view_testmaster"]),
    ("protocol", "Protocol Master", ["add_protocolmaster", "change_protocolmaster", "delete_protocolmaster", "view_protocolmaster"]),
    ("uom", "UOM Master", ["add_uommaster", "change_uommaster", "delete_uommaster", "view_uommaster"]),
    ("remark", "Remark Master", ["add_reportremark", "change_reportremark", "delete_reportremark", "view_reportremark"]),
    ("tds", "TDS Master", ["add_tdsdocumenttemplate", "change_tdsdocumenttemplate", "delete_tdsdocumenttemplate", "view_tdsdocumenttemplate"]),
]


def _master_permissions_for_keys(keys):
    permission_codenames = {
        codename
        for key, _label, codenames in MASTER_ACCESS_OPTIONS
        if key in set(keys or [])
        for codename in codenames
    }
    return list(Permission.objects.filter(codename__in=permission_codenames))


def _selected_master_access_keys(user):
    user_permission_codenames = set(user.user_permissions.values_list("codename", flat=True))
    return [
        key
        for key, _label, codenames in MASTER_ACCESS_OPTIONS
        if set(codenames).issubset(user_permission_codenames)
    ]


def _delete_booking_permission():
    return Permission.objects.filter(
        content_type__app_label="bookings",
        codename="delete_booking",
    ).first()


def _permission(app_label, codename):
    return Permission.objects.filter(
        content_type__app_label=app_label,
        codename=codename,
    ).first()


def _billing_permissions():
    return list(Permission.objects.filter(
        content_type__app_label="bookings",
        codename__in=["add_billingrecord", "delete_billingrecord", "view_billingrecord"],
    ))


def _letterhead_permission():
    return _permission("reports", "manage_letterheads")


def _user_management_permission():
    return _permission("accounts", "manage_users")


DELEGATED_PERMISSION_FIELDS = {
    "can_delete_bookings": [("bookings", "delete_booking")],
    "can_view_data_sheet": [("bookings", "view_data_sheet")],
    "can_view_user_activity": [("accounts", "view_user_activity")],
    "can_manage_billing": [("bookings", "view_billingrecord")],
    "can_manage_welcome_announcement": [("accounts", "manage_welcome_announcement")],
    "can_manage_system_settings": [("accounts", "manage_system_settings")],
    "can_edit_tinymce_source": [("accounts", "edit_tinymce_source")],
    "can_manage_letterheads": [("reports", "manage_letterheads")],
    "can_manage_users": [("accounts", "manage_users")],
    "can_assign_bookings": [("bookings", "assign_booking")],
}


def _restrict_delegated_access(form, grantor):
    """Limit a delegated administrator to roles and permissions they possess."""
    form.grantor = grantor
    form.is_delegated_admin = bool(grantor and not grantor.is_superuser)
    if not form.is_delegated_admin:
        return

    grantor_permissions = grantor.get_all_permissions()
    allowed_permission_codenames = [key.split(".", 1)[1] for key in grantor_permissions if "." in key]
    form.fields["permissions"].queryset = form.fields["permissions"].queryset.filter(
        codename__in=allowed_permission_codenames
    )
    form.fields["groups"].queryset = grantor.groups.filter(
        name__in=["Manager", "Analyst"]
    ).order_by("name")
    form.fields["master_access"].choices = [
        (key, label)
        for key, label, _codenames in MASTER_ACCESS_OPTIONS
        if all(
            f"{permission.content_type.app_label}.{permission.codename}" in grantor_permissions
            for permission in _master_permissions_for_keys([key])
        )
    ]

    for field_name, permission_keys in DELEGATED_PERMISSION_FIELDS.items():
        is_allowed = all(
                f"{app_label}.{codename}" in grantor_permissions
                for app_label, codename in permission_keys
            )
        if field_name in form.fields and not is_allowed:
            form.fields[field_name].disabled = True

    if "is_staff" in form.fields and not grantor.is_staff:
        form.fields["is_staff"].disabled = True
    if "is_checked_by" in form.fields and not grantor.groups.filter(name="Checked By").exists():
        form.fields["is_checked_by"].disabled = True
    if "is_person_incharge" in form.fields and not grantor.groups.filter(name="Incharge").exists():
        form.fields["is_person_incharge"].disabled = True


def _preserve_unguardable_permissions(form, user, selected_permissions):
    """Do not let delegated administrators remove permissions outside their scope."""
    if not getattr(form, "is_delegated_admin", False) or not form._editing_existing:
        return selected_permissions
    allowed_keys = form.grantor.get_all_permissions()
    allowed_codenames = [key.split(".", 1)[1] for key in allowed_keys if "." in key]
    preserved = user.user_permissions.exclude(codename__in=allowed_codenames)
    return list(selected_permissions) + list(preserved)


class WelcomeAnnouncementForm(forms.ModelForm):
    class Meta:
        model = WelcomeAnnouncement
        fields = ["announcement_type", "is_active", "title", "message", "image", "button_text", "button_action", "button_url", "start_date", "end_date", "display_mode", "presentation", "allow_close"]
        widgets = {
            "announcement_type": forms.TextInput(attrs={"class": "form-control", "placeholder": "Welcome, Good Morning, Launch Party, Maintenance…"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "Welcome to ARL LIMS"}),
            "message": forms.Textarea(attrs={"class": "form-control", "data-editor": "announcement-tinymce", "rows": 10}),
            "image": forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/*"}),
            "button_text": forms.TextInput(attrs={"class": "form-control", "placeholder": "Get Started"}),
            "button_action": forms.Select(attrs={"class": "form-select"}),
            "button_url": forms.TextInput(attrs={"class": "form-control", "placeholder": "https://… or /bookings/"}),
            "start_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "end_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "display_mode": forms.Select(attrs={"class": "form-select"}),
            "presentation": forms.Select(attrs={"class": "form-select"}),
            "allow_close": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_button_url(self):
        value = (self.cleaned_data.get("button_url") or "").strip()
        action = self.cleaned_data.get("button_action")
        if action == WelcomeAnnouncement.ButtonAction.INTERNAL and value and not value.startswith("/"):
            raise forms.ValidationError("Internal pages must start with /. ")
        if action == WelcomeAnnouncement.ButtonAction.URL and value and not value.startswith(("https://", "http://")):
            raise forms.ValidationError("Use a full http:// or https:// URL.")
        return value


class SystemSettingForm(forms.ModelForm):
    class Meta:
        model = SystemSetting
        fields = [
            "login_enabled",
            "session_timeout_minutes",
            "certificate_numbering_mode",
        ]
        widgets = {
            "login_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "session_timeout_minutes": forms.NumberInput(attrs={"class": "form-control", "min": 0, "max": 10080}),
            "certificate_numbering_mode": forms.Select(attrs={"class": "form-select"}),
        }


class LoginForm(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={"class": "form-control"}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={"class": "form-control", "maxlength": "16"}))

    error_messages = {
        "invalid_login": "Invalid username or password.",
        "inactive": "Invalid username or password.",
    }

    def clean(self):
        try:
            return super().clean()
        except forms.ValidationError:
            username = self.cleaned_data.get("username")
            password = self.cleaned_data.get("password")
            if username and password:
                self._record_failed_attempt(username, password)
            raise

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        UserProfile.objects.filter(user=user).update(failed_login_attempts=0, locked_at=None)

    @staticmethod
    def _record_failed_attempt(username, password):
        """Lock only a known account with an incorrect password, silently."""
        user_model = get_user_model()
        with transaction.atomic():
            user = user_model.objects.select_for_update().filter(username=username).first()
            if not user or not user.is_active or user.check_password(password):
                return
            profile, _ = UserProfile.objects.select_for_update().get_or_create(user=user)
            profile.failed_login_attempts += 1
            update_fields = ["failed_login_attempts"]
            if profile.failed_login_attempts >= 3:
                user.is_active = False
                user.save(update_fields=["is_active"])
                profile.locked_at = timezone.now()
                update_fields.append("locked_at")
            profile.save(update_fields=update_fields)


class AdminUserCreateForm(UserCreationForm):
    email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={"class": "form-control"}))
    is_staff = forms.BooleanField(required=False)
    is_checked_by = forms.BooleanField(required=False, label="Checked By")
    is_person_incharge = forms.BooleanField(required=False, label="Person In-charge")
    can_delete_bookings = forms.BooleanField(required=False, label="Delete Booking Access")
    can_view_data_sheet = forms.BooleanField(required=False, label="Data Sheet Access")
    can_view_user_activity = forms.BooleanField(required=False, label="User Activity Access")
    can_manage_billing = forms.BooleanField(required=False, label="Bill Invoice")
    can_manage_welcome_announcement = forms.BooleanField(required=False, label="Welcome Announcement")
    can_manage_system_settings = forms.BooleanField(required=False, label="System Settings")
    can_edit_tinymce_source = forms.BooleanField(required=False, label="TinyMCE Source Code")
    can_manage_letterheads = forms.BooleanField(required=False, label="Letterhead Upload")
    can_manage_users = forms.BooleanField(required=False, label="User Management")
    can_assign_bookings = forms.BooleanField(required=False, label="Assign Bookings")
    master_access = forms.MultipleChoiceField(
        choices=[(key, label) for key, label, _codenames in MASTER_ACCESS_OPTIONS],
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Master Access",
    )
    signature_file = forms.FileField(required=False)
    first_name = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    last_name = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.filter(name__in=["Admin", "Manager", "Analyst"]).order_by("name"),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.filter(
            codename__in=[
                'add_booking', 'change_booking', 'view_booking',
                'add_report', 'change_report', 'delete_report', 'view_report',
            ]
        ).order_by('content_type__app_label', 'codename'),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Direct Permissions",
        help_text="Assign bookings and reports permissions directly to this user.",
    )

    class Meta:
        model = User
        fields = (
            "username",
            "first_name",
            "last_name",
            "email",
            "password1",
            "password2",
            "is_staff",
            "is_checked_by",
            "is_person_incharge",
            "master_access",
            "can_delete_bookings",
            "can_view_data_sheet",
            "can_view_user_activity",
            "can_manage_billing",
            "can_manage_welcome_announcement",
            "can_manage_system_settings", "can_edit_tinymce_source",
            "can_manage_letterheads",
            "can_manage_users",
            "can_assign_bookings",
            "signature_file",
            "groups",
            "permissions",
        )

    def __init__(self, *args, **kwargs):
        grantor = kwargs.pop("grantor", None)
        super().__init__(*args, **kwargs)
        self._editing_existing = False
        _restrict_delegated_access(self, grantor)
        self.fields["username"].widget.attrs["class"] = "form-control"
        self.fields["password1"].widget.attrs.update({"class": "form-control", "maxlength": "16"})
        self.fields["password2"].widget.attrs.update({"class": "form-control", "maxlength": "16"})
        self.fields["is_staff"].widget.attrs["class"] = "form-check-input"
        self.fields["is_checked_by"].widget.attrs["class"] = "form-check-input"
        self.fields["is_person_incharge"].widget.attrs["class"] = "form-check-input"
        self.fields["can_delete_bookings"].widget.attrs["class"] = "form-check-input"
        self.fields["can_view_data_sheet"].widget.attrs["class"] = "form-check-input"
        self.fields["can_view_user_activity"].widget.attrs["class"] = "form-check-input"
        self.fields["can_manage_billing"].widget.attrs["class"] = "form-check-input"
        self.fields["can_manage_welcome_announcement"].widget.attrs["class"] = "form-check-input"
        self.fields["can_manage_system_settings"].widget.attrs["class"] = "form-check-input"
        self.fields["can_edit_tinymce_source"].widget.attrs["class"] = "form-check-input"
        self.fields["can_manage_letterheads"].widget.attrs["class"] = "form-check-input"
        self.fields["can_manage_users"].widget.attrs["class"] = "form-check-input"
        self.fields["can_assign_bookings"].widget.attrs["class"] = "form-check-input"
        self.fields["signature_file"].widget.attrs["class"] = "form-control"
        self.fields["permissions"].widget.attrs["class"] = "form-check-input"

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data.get("email", "")
        user.first_name = (self.cleaned_data.get("first_name") or "").strip()
        user.last_name = (self.cleaned_data.get("last_name") or "").strip()
        checked_by = bool(self.cleaned_data.get("is_checked_by"))
        person_incharge = bool(self.cleaned_data.get("is_person_incharge"))
        master_access = self.cleaned_data.get("master_access") or []
        can_delete_bookings = bool(self.cleaned_data.get("can_delete_bookings"))
        can_view_data_sheet = bool(self.cleaned_data.get("can_view_data_sheet"))
        can_view_user_activity = bool(self.cleaned_data.get("can_view_user_activity"))
        can_manage_billing = bool(self.cleaned_data.get("can_manage_billing"))
        can_manage_welcome_announcement = bool(self.cleaned_data.get("can_manage_welcome_announcement"))
        can_manage_system_settings = bool(self.cleaned_data.get("can_manage_system_settings"))
        can_edit_tinymce_source = bool(self.cleaned_data.get("can_edit_tinymce_source"))
        can_manage_letterheads = bool(self.cleaned_data.get("can_manage_letterheads"))
        can_manage_users = bool(self.cleaned_data.get("can_manage_users"))
        can_assign_bookings = bool(self.cleaned_data.get("can_assign_bookings"))
        can_assign_bookings = bool(self.cleaned_data.get("can_assign_bookings"))
        user.is_staff = bool(self.cleaned_data.get("is_staff", False)) or checked_by or person_incharge
        user.is_active = True
        if commit:
            user.save()
            user.groups.set(self.cleaned_data.get("groups"))
            selected_permissions = list(self.cleaned_data.get("permissions") or [])
            selected_permissions.extend(_master_permissions_for_keys(master_access))
            if can_delete_bookings:
                delete_booking_permission = _delete_booking_permission()
                if delete_booking_permission:
                    selected_permissions.append(delete_booking_permission)
            if can_view_data_sheet:
                data_sheet_permission = _permission("bookings", "view_data_sheet")
                if data_sheet_permission:
                    selected_permissions.append(data_sheet_permission)
            if can_view_user_activity:
                user_activity_permission = _permission("accounts", "view_user_activity")
                if user_activity_permission:
                    selected_permissions.append(user_activity_permission)
            if can_manage_billing:
                selected_permissions.extend(_billing_permissions())
            if can_manage_welcome_announcement:
                permission = _permission("accounts", "manage_welcome_announcement")
                if permission:
                    selected_permissions.append(permission)
            if can_manage_system_settings:
                permission = _permission("accounts", "manage_system_settings")
                if permission:
                    selected_permissions.append(permission)
            if can_edit_tinymce_source:
                permission = _permission("accounts", "edit_tinymce_source")
                if permission:
                    selected_permissions.append(permission)
            if can_manage_letterheads:
                permission = _letterhead_permission()
                if permission:
                    selected_permissions.append(permission)
            if can_manage_users:
                permission = _user_management_permission()
                if permission:
                    selected_permissions.append(permission)
            if can_assign_bookings:
                assign_perm = _permission("bookings", "assign_booking")
                if assign_perm:
                    selected_permissions.append(assign_perm)
            # handle assign booking permission
            if getattr(self, 'is_delegated_admin', False):
                # delegated admin may not be allowed to toggle this; _preserve_unguardable_permissions will handle preserving
                pass
            if self.cleaned_data.get("can_assign_bookings"):
                assign_perm = _permission("bookings", "assign_booking")
                if assign_perm:
                    selected_permissions.append(assign_perm)
            if can_assign_bookings:
                permission = _permission("bookings", "assign_booking")
                if permission:
                    selected_permissions.append(permission)
            selected_permissions = _preserve_unguardable_permissions(self, user, selected_permissions)
            unique_permissions = {permission.pk: permission for permission in selected_permissions}
            user.user_permissions.set(unique_permissions.values())
            if user.is_staff:
                staff_group, _ = Group.objects.get_or_create(name="Staff")
                staff_group.user_set.add(user)
            if checked_by:
                group, _ = Group.objects.get_or_create(name="Checked By")
                group.user_set.add(user)
            if person_incharge:
                group, _ = Group.objects.get_or_create(name="Incharge")
                group.user_set.add(user)

            signature_file = self.cleaned_data.get("signature_file")
            if signature_file:
                profile, _ = UserProfile.objects.get_or_create(user=user)
                profile.signature_file = signature_file
                profile.save(update_fields=["signature_file"])
        return user


class AdminUserUpdateForm(forms.ModelForm):
    email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={"class": "form-control"}))
    is_staff = forms.BooleanField(required=False)
    is_active = forms.BooleanField(required=False)
    is_checked_by = forms.BooleanField(required=False, label="Checked By")
    is_person_incharge = forms.BooleanField(required=False, label="Person In-charge")
    can_delete_bookings = forms.BooleanField(required=False, label="Delete Booking Access")
    can_view_data_sheet = forms.BooleanField(required=False, label="Data Sheet Access")
    can_view_user_activity = forms.BooleanField(required=False, label="User Activity Access")
    can_manage_billing = forms.BooleanField(required=False, label="Bill Invoice")
    can_manage_welcome_announcement = forms.BooleanField(required=False, label="Welcome Announcement")
    can_manage_system_settings = forms.BooleanField(required=False, label="System Settings")
    can_edit_tinymce_source = forms.BooleanField(required=False, label="TinyMCE Source Code")
    can_manage_letterheads = forms.BooleanField(required=False, label="Letterhead Upload")
    can_manage_users = forms.BooleanField(required=False, label="User Management")
    can_assign_bookings = forms.BooleanField(required=False, label="Assign Bookings")
    master_access = forms.MultipleChoiceField(
        choices=[(key, label) for key, label, _codenames in MASTER_ACCESS_OPTIONS],
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Master Access",
    )
    signature_file = forms.FileField(required=False)
    first_name = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    last_name = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.filter(name__in=["Admin", "Manager", "Analyst"]).order_by("name"),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.filter(
            codename__in=[
                'add_booking', 'change_booking', 'view_booking',
                'add_report', 'change_report', 'delete_report', 'view_report',
            ]
        ).order_by('content_type__app_label', 'codename'),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Direct Permissions",
        help_text="Assign bookings and reports permissions directly to this user.",
    )

    class Meta:
        model = User
        fields = (
            "username",
            "first_name",
            "last_name",
            "email",
            "is_active",
            "is_staff",
            "is_checked_by",
            "is_person_incharge",
            "master_access",
            "can_delete_bookings",
            "can_view_data_sheet",
            "can_view_user_activity",
            "can_manage_billing",
            "can_manage_welcome_announcement",
            "can_manage_system_settings", "can_edit_tinymce_source",
            "can_manage_letterheads",
            "can_manage_users",
            "can_assign_bookings",
            "signature_file",
            "groups",
            "permissions",
        )

    def __init__(self, *args, **kwargs):
        grantor = kwargs.pop("grantor", None)
        super().__init__(*args, **kwargs)
        self._editing_existing = bool(self.instance and self.instance.pk)
        _restrict_delegated_access(self, grantor)

        self.fields["username"].widget.attrs["class"] = "form-control"
        self.fields["first_name"].widget.attrs["class"] = "form-control"
        self.fields["last_name"].widget.attrs["class"] = "form-control"
        self.fields["is_staff"].widget.attrs["class"] = "form-check-input"
        self.fields["is_active"].widget.attrs["class"] = "form-check-input"
        self.fields["is_checked_by"].widget.attrs["class"] = "form-check-input"
        self.fields["is_person_incharge"].widget.attrs["class"] = "form-check-input"
        self.fields["can_delete_bookings"].widget.attrs["class"] = "form-check-input"
        self.fields["can_view_data_sheet"].widget.attrs["class"] = "form-check-input"
        self.fields["can_view_user_activity"].widget.attrs["class"] = "form-check-input"
        self.fields["can_manage_billing"].widget.attrs["class"] = "form-check-input"
        self.fields["can_manage_welcome_announcement"].widget.attrs["class"] = "form-check-input"
        self.fields["can_manage_system_settings"].widget.attrs["class"] = "form-check-input"
        self.fields["can_edit_tinymce_source"].widget.attrs["class"] = "form-check-input"
        self.fields["can_manage_letterheads"].widget.attrs["class"] = "form-check-input"
        self.fields["can_manage_users"].widget.attrs["class"] = "form-check-input"
        self.fields["signature_file"].widget.attrs["class"] = "form-control"
        self.fields["permissions"].widget.attrs["class"] = "form-check-input"
        self.fields["can_assign_bookings"].widget.attrs["class"] = "form-check-input"

        if self.instance and getattr(self.instance, "pk", None):
            self.fields["is_active"].initial = bool(self.instance.is_active)
            self.fields["is_staff"].initial = bool(self.instance.is_staff)
            self.fields["is_checked_by"].initial = self.instance.groups.filter(name="Checked By").exists()
            self.fields["is_person_incharge"].initial = self.instance.groups.filter(name="Incharge").exists()
            self.fields["permissions"].initial = self.instance.user_permissions.all()
            self.fields["master_access"].initial = _selected_master_access_keys(self.instance)
            self.fields["can_delete_bookings"].initial = self.instance.user_permissions.filter(
                content_type__app_label="bookings",
                codename="delete_booking",
            ).exists()
            self.fields["can_view_data_sheet"].initial = self.instance.user_permissions.filter(
                content_type__app_label="bookings", codename="view_data_sheet"
            ).exists()
            self.fields["can_view_user_activity"].initial = self.instance.user_permissions.filter(
                content_type__app_label="accounts", codename="view_user_activity"
            ).exists()
            self.fields["can_manage_billing"].initial = self.instance.user_permissions.filter(
                content_type__app_label="bookings", codename="view_billingrecord"
            ).exists()
            self.fields["can_manage_welcome_announcement"].initial = self.instance.user_permissions.filter(
                content_type__app_label="accounts", codename="manage_welcome_announcement"
            ).exists()
            self.fields["can_manage_system_settings"].initial = self.instance.user_permissions.filter(
                content_type__app_label="accounts", codename="manage_system_settings"
            ).exists()
            self.fields["can_edit_tinymce_source"].initial = self.instance.user_permissions.filter(
                content_type__app_label="accounts", codename="edit_tinymce_source"
            ).exists()
            self.fields["can_manage_letterheads"].initial = self.instance.user_permissions.filter(
                content_type__app_label="reports", codename="manage_letterheads"
            ).exists()
            self.fields["can_manage_users"].initial = self.instance.user_permissions.filter(
                content_type__app_label="accounts", codename="manage_users"
            ).exists()
            self.fields["can_assign_bookings"].initial = self.instance.user_permissions.filter(
                content_type__app_label="bookings", codename="assign_booking"
            ).exists()
        if not (grantor and grantor.is_superuser):
            self.fields["is_active"].disabled = True

    def save(self, commit=True):
        originally_active = bool(self.instance.is_active)
        user = super().save(commit=False)
        user.email = self.cleaned_data.get("email", "")
        user.first_name = (self.cleaned_data.get("first_name") or "").strip()
        user.last_name = (self.cleaned_data.get("last_name") or "").strip()

        checked_by = bool(self.cleaned_data.get("is_checked_by"))
        person_incharge = bool(self.cleaned_data.get("is_person_incharge"))
        master_access = self.cleaned_data.get("master_access") or []
        can_delete_bookings = bool(self.cleaned_data.get("can_delete_bookings"))
        can_view_data_sheet = bool(self.cleaned_data.get("can_view_data_sheet"))
        can_view_user_activity = bool(self.cleaned_data.get("can_view_user_activity"))
        can_manage_billing = bool(self.cleaned_data.get("can_manage_billing"))
        can_manage_welcome_announcement = bool(self.cleaned_data.get("can_manage_welcome_announcement"))
        can_manage_system_settings = bool(self.cleaned_data.get("can_manage_system_settings"))
        can_edit_tinymce_source = bool(self.cleaned_data.get("can_edit_tinymce_source"))
        can_manage_letterheads = bool(self.cleaned_data.get("can_manage_letterheads"))
        can_manage_users = bool(self.cleaned_data.get("can_manage_users"))
        can_assign_bookings = bool(self.cleaned_data.get("can_assign_bookings"))
        user.is_active = bool(self.cleaned_data.get("is_active", True)) if not self.fields["is_active"].disabled else self.instance.is_active
        user.is_staff = bool(self.cleaned_data.get("is_staff", False)) or checked_by or person_incharge

        if commit:
            user.save()

            managed_group_names = {"Admin", "Manager", "Analyst", "Checked By", "Incharge", "Staff"}
            existing_groups = list(user.groups.all())
            if self.is_delegated_admin:
                manageable_group_names = set(self.fields["groups"].queryset.values_list("name", flat=True))
                if not self.fields["is_staff"].disabled:
                    manageable_group_names.add("Staff")
                if not self.fields["is_checked_by"].disabled:
                    manageable_group_names.add("Checked By")
                if not self.fields["is_person_incharge"].disabled:
                    manageable_group_names.add("Incharge")
                preserved_groups = [g for g in existing_groups if g.name not in manageable_group_names]
            else:
                preserved_groups = [g for g in existing_groups if g.name not in managed_group_names]

            selected_groups = list(self.cleaned_data.get("groups") or [])
            desired_groups = preserved_groups + selected_groups

            staff_group, _ = Group.objects.get_or_create(name="Staff")
            checked_by_group, _ = Group.objects.get_or_create(name="Checked By")
            incharge_group, _ = Group.objects.get_or_create(name="Incharge")

            if user.is_staff and staff_group not in desired_groups:
                desired_groups.append(staff_group)
            if checked_by and checked_by_group not in desired_groups:
                desired_groups.append(checked_by_group)
            if not checked_by and checked_by_group in desired_groups:
                desired_groups = [g for g in desired_groups if g.pk != checked_by_group.pk]
            if person_incharge and incharge_group not in desired_groups:
                desired_groups.append(incharge_group)
            if not person_incharge and incharge_group in desired_groups:
                desired_groups = [g for g in desired_groups if g.pk != incharge_group.pk]

            if not user.is_staff and staff_group in desired_groups:
                desired_groups = [g for g in desired_groups if g.pk != staff_group.pk]

            user.groups.set(desired_groups)
            # A superuser can reactivate a locked account; assigning the Admin
            # role also restores the account as requested.
            if any(group.name == "Admin" for group in desired_groups):
                user.is_active = True
            if user.is_active and not originally_active:
                profile, _ = UserProfile.objects.get_or_create(user=user)
                profile.failed_login_attempts = 0
                profile.locked_at = None
                profile.save(update_fields=["failed_login_attempts", "locked_at"])
            user.save(update_fields=["is_active"])
            selected_permissions = list(self.cleaned_data.get("permissions") or [])
            selected_permissions.extend(_master_permissions_for_keys(master_access))
            if can_delete_bookings:
                delete_booking_permission = _delete_booking_permission()
                if delete_booking_permission:
                    selected_permissions.append(delete_booking_permission)
            if can_view_data_sheet:
                data_sheet_permission = _permission("bookings", "view_data_sheet")
                if data_sheet_permission:
                    selected_permissions.append(data_sheet_permission)
            if can_view_user_activity:
                user_activity_permission = _permission("accounts", "view_user_activity")
                if user_activity_permission:
                    selected_permissions.append(user_activity_permission)
            if can_manage_billing:
                selected_permissions.extend(_billing_permissions())
            if can_manage_welcome_announcement:
                permission = _permission("accounts", "manage_welcome_announcement")
                if permission:
                    selected_permissions.append(permission)
            if can_manage_system_settings:
                permission = _permission("accounts", "manage_system_settings")
                if permission:
                    selected_permissions.append(permission)
            if can_edit_tinymce_source:
                permission = _permission("accounts", "edit_tinymce_source")
                if permission:
                    selected_permissions.append(permission)
            if can_manage_letterheads:
                permission = _letterhead_permission()
                if permission:
                    selected_permissions.append(permission)
            if can_manage_users:
                permission = _user_management_permission()
                if permission:
                    selected_permissions.append(permission)
            if can_assign_bookings:
                assign_perm = _permission("bookings", "assign_booking")
                if assign_perm:
                    selected_permissions.append(assign_perm)
            selected_permissions = _preserve_unguardable_permissions(self, user, selected_permissions)
            unique_permissions = {permission.pk: permission for permission in selected_permissions}
            user.user_permissions.set(unique_permissions.values())

            signature_clear = self.data.get("signature_file-clear") == "on"
            signature_file = self.cleaned_data.get("signature_file")
            if signature_clear or signature_file:
                profile, _ = UserProfile.objects.get_or_create(user=user)
                if signature_clear:
                    if profile.signature_file:
                        profile.signature_file.delete(save=False)
                    profile.signature_file = None
                else:
                    profile.signature_file = signature_file
                profile.save()

        return user
