from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import Group, Permission, User

from .models import SystemSetting, UserProfile, WelcomeAnnouncement


MASTER_PERMISSION_CODENAMES = [
    "add_customermaster", "change_customermaster", "delete_customermaster", "view_customermaster",
    "add_submittermaster", "change_submittermaster", "delete_submittermaster", "view_submittermaster",
    "add_manufacturermaster", "change_manufacturermaster", "delete_manufacturermaster", "view_manufacturermaster",
    "add_samplenamemaster", "change_samplenamemaster", "delete_samplenamemaster", "view_samplenamemaster",
    "add_testmaster", "change_testmaster", "delete_testmaster", "view_testmaster",
    "add_protocolmaster", "change_protocolmaster", "delete_protocolmaster", "view_protocolmaster",
    "add_uommaster", "change_uommaster", "delete_uommaster", "view_uommaster",
    "add_reportremark", "change_reportremark", "delete_reportremark", "view_reportremark",
]


def _master_permissions_queryset():
    return Permission.objects.filter(codename__in=MASTER_PERMISSION_CODENAMES).order_by(
        "content_type__app_label", "codename"
    )


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
            "allow_manual_sample_reg_no",
            "allow_manual_certificate_no",
        ]
        widgets = {
            "login_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "session_timeout_minutes": forms.NumberInput(attrs={"class": "form-control", "min": 0, "max": 10080}),
            "certificate_numbering_mode": forms.Select(attrs={"class": "form-select"}),
            "allow_manual_sample_reg_no": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "allow_manual_certificate_no": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class LoginForm(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={"class": "form-control"}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={"class": "form-control"}))

    error_messages = {
        "invalid_login": "Invalid username or password.",
        "inactive": "This user account is inactive.",
    }


class AdminUserCreateForm(UserCreationForm):
    email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={"class": "form-control"}))
    is_staff = forms.BooleanField(required=False)
    is_checked_by = forms.BooleanField(required=False, label="Checked By")
    is_person_incharge = forms.BooleanField(required=False, label="Person In-charge")
    can_edit_masters = forms.BooleanField(required=False, label="Edit Masters")
    can_delete_bookings = forms.BooleanField(required=False, label="Delete Booking Access")
    can_view_data_sheet = forms.BooleanField(required=False, label="Data Sheet Access")
    can_view_user_activity = forms.BooleanField(required=False, label="User Activity Access")
    can_manage_billing = forms.BooleanField(required=False, label="Bill Invoice")
    can_manage_welcome_announcement = forms.BooleanField(required=False, label="Welcome Announcement")
    can_manage_system_settings = forms.BooleanField(required=False, label="System Settings")
    can_edit_tinymce_source = forms.BooleanField(required=False, label="TinyMCE Source Code")
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
            "can_edit_masters",
            "can_delete_bookings",
            "can_view_data_sheet",
            "can_view_user_activity",
            "can_manage_billing",
            "can_manage_welcome_announcement",
            "can_manage_system_settings", "can_edit_tinymce_source",
            "signature_file",
            "groups",
            "permissions",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs["class"] = "form-control"
        self.fields["password1"].widget.attrs["class"] = "form-control"
        self.fields["password2"].widget.attrs["class"] = "form-control"
        self.fields["is_staff"].widget.attrs["class"] = "form-check-input"
        self.fields["is_checked_by"].widget.attrs["class"] = "form-check-input"
        self.fields["is_person_incharge"].widget.attrs["class"] = "form-check-input"
        self.fields["can_edit_masters"].widget.attrs["class"] = "form-check-input"
        self.fields["can_delete_bookings"].widget.attrs["class"] = "form-check-input"
        self.fields["can_view_data_sheet"].widget.attrs["class"] = "form-check-input"
        self.fields["can_view_user_activity"].widget.attrs["class"] = "form-check-input"
        self.fields["can_manage_billing"].widget.attrs["class"] = "form-check-input"
        self.fields["can_manage_welcome_announcement"].widget.attrs["class"] = "form-check-input"
        self.fields["can_manage_system_settings"].widget.attrs["class"] = "form-check-input"
        self.fields["can_edit_tinymce_source"].widget.attrs["class"] = "form-check-input"
        self.fields["signature_file"].widget.attrs["class"] = "form-control"
        self.fields["permissions"].widget.attrs["class"] = "form-check-input"

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data.get("email", "")
        user.first_name = (self.cleaned_data.get("first_name") or "").strip()
        user.last_name = (self.cleaned_data.get("last_name") or "").strip()
        checked_by = bool(self.cleaned_data.get("is_checked_by"))
        person_incharge = bool(self.cleaned_data.get("is_person_incharge"))
        can_edit_masters = bool(self.cleaned_data.get("can_edit_masters"))
        can_delete_bookings = bool(self.cleaned_data.get("can_delete_bookings"))
        can_view_data_sheet = bool(self.cleaned_data.get("can_view_data_sheet"))
        can_view_user_activity = bool(self.cleaned_data.get("can_view_user_activity"))
        can_manage_billing = bool(self.cleaned_data.get("can_manage_billing"))
        can_manage_welcome_announcement = bool(self.cleaned_data.get("can_manage_welcome_announcement"))
        can_manage_system_settings = bool(self.cleaned_data.get("can_manage_system_settings"))
        can_edit_tinymce_source = bool(self.cleaned_data.get("can_edit_tinymce_source"))
        user.is_staff = bool(self.cleaned_data.get("is_staff", False)) or checked_by or person_incharge
        if commit:
            user.save()
            user.groups.set(self.cleaned_data.get("groups"))
            selected_permissions = list(self.cleaned_data.get("permissions") or [])
            if can_edit_masters:
                selected_permissions.extend(list(_master_permissions_queryset()))
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
    can_edit_masters = forms.BooleanField(required=False, label="Edit Masters")
    can_delete_bookings = forms.BooleanField(required=False, label="Delete Booking Access")
    can_view_data_sheet = forms.BooleanField(required=False, label="Data Sheet Access")
    can_view_user_activity = forms.BooleanField(required=False, label="User Activity Access")
    can_manage_billing = forms.BooleanField(required=False, label="Bill Invoice")
    can_manage_welcome_announcement = forms.BooleanField(required=False, label="Welcome Announcement")
    can_manage_system_settings = forms.BooleanField(required=False, label="System Settings")
    can_edit_tinymce_source = forms.BooleanField(required=False, label="TinyMCE Source Code")
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
            "can_edit_masters",
            "can_delete_bookings",
            "can_view_data_sheet",
            "can_view_user_activity",
            "can_manage_billing",
            "can_manage_welcome_announcement",
            "can_manage_system_settings", "can_edit_tinymce_source",
            "signature_file",
            "groups",
            "permissions",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["username"].widget.attrs["class"] = "form-control"
        self.fields["first_name"].widget.attrs["class"] = "form-control"
        self.fields["last_name"].widget.attrs["class"] = "form-control"
        self.fields["is_staff"].widget.attrs["class"] = "form-check-input"
        self.fields["is_active"].widget.attrs["class"] = "form-check-input"
        self.fields["is_checked_by"].widget.attrs["class"] = "form-check-input"
        self.fields["is_person_incharge"].widget.attrs["class"] = "form-check-input"
        self.fields["can_edit_masters"].widget.attrs["class"] = "form-check-input"
        self.fields["can_delete_bookings"].widget.attrs["class"] = "form-check-input"
        self.fields["can_view_data_sheet"].widget.attrs["class"] = "form-check-input"
        self.fields["can_view_user_activity"].widget.attrs["class"] = "form-check-input"
        self.fields["can_manage_billing"].widget.attrs["class"] = "form-check-input"
        self.fields["can_manage_welcome_announcement"].widget.attrs["class"] = "form-check-input"
        self.fields["can_manage_system_settings"].widget.attrs["class"] = "form-check-input"
        self.fields["can_edit_tinymce_source"].widget.attrs["class"] = "form-check-input"
        self.fields["signature_file"].widget.attrs["class"] = "form-control"
        self.fields["permissions"].widget.attrs["class"] = "form-check-input"

        if self.instance and getattr(self.instance, "pk", None):
            self.fields["is_active"].initial = bool(self.instance.is_active)
            self.fields["is_staff"].initial = bool(self.instance.is_staff)
            self.fields["is_checked_by"].initial = self.instance.groups.filter(name="Checked By").exists()
            self.fields["is_person_incharge"].initial = self.instance.groups.filter(name="Incharge").exists()
            self.fields["permissions"].initial = self.instance.user_permissions.all()
            self.fields["can_edit_masters"].initial = self.instance.user_permissions.filter(
                codename__in=MASTER_PERMISSION_CODENAMES
            ).exists()
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

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data.get("email", "")
        user.first_name = (self.cleaned_data.get("first_name") or "").strip()
        user.last_name = (self.cleaned_data.get("last_name") or "").strip()

        checked_by = bool(self.cleaned_data.get("is_checked_by"))
        person_incharge = bool(self.cleaned_data.get("is_person_incharge"))
        can_edit_masters = bool(self.cleaned_data.get("can_edit_masters"))
        can_delete_bookings = bool(self.cleaned_data.get("can_delete_bookings"))
        can_view_data_sheet = bool(self.cleaned_data.get("can_view_data_sheet"))
        can_view_user_activity = bool(self.cleaned_data.get("can_view_user_activity"))
        can_manage_billing = bool(self.cleaned_data.get("can_manage_billing"))
        can_manage_welcome_announcement = bool(self.cleaned_data.get("can_manage_welcome_announcement"))
        can_manage_system_settings = bool(self.cleaned_data.get("can_manage_system_settings"))
        can_edit_tinymce_source = bool(self.cleaned_data.get("can_edit_tinymce_source"))
        user.is_active = bool(self.cleaned_data.get("is_active", True))
        user.is_staff = bool(self.cleaned_data.get("is_staff", False)) or checked_by or person_incharge

        if commit:
            user.save()

            managed_group_names = {"Admin", "Manager", "Analyst", "Checked By", "Incharge", "Staff"}
            existing_groups = list(user.groups.all())
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
            selected_permissions = list(self.cleaned_data.get("permissions") or [])
            if can_edit_masters:
                selected_permissions.extend(list(_master_permissions_queryset()))
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
