from django.contrib import messages
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.core.files.storage import default_storage
from PIL import Image
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, ListView, UpdateView
from django.db.models import Q
from django.db.models.deletion import ProtectedError

from .forms import AdminUserCreateForm, AdminUserUpdateForm, LoginForm, SystemSettingForm, WelcomeAnnouncementForm
from .models import AnnouncementSeen, SystemSetting, UserActivity, WelcomeAnnouncement


class UserLoginView(LoginView):
    template_name = 'registration/login.html'
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def dispatch(self, request, *args, **kwargs):
        from django.db import DatabaseError
        try:
            if request.method == "POST" and not SystemSetting.current().login_enabled:
                messages.error(request, "Login is currently disabled by the administrator.")
                return redirect("accounts:login")
        except DatabaseError:
            pass
        return super().dispatch(request, *args, **kwargs)


class UserLogoutView(LogoutView):
    next_page = reverse_lazy('accounts:login')


class WelcomeAnnouncementUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    template_name = "accounts/welcome_announcement_form.html"
    form_class = WelcomeAnnouncementForm
    success_url = reverse_lazy("dashboard")

    def test_func(self):
        return self.request.user.is_superuser or self.request.user.has_perm("accounts.manage_welcome_announcement")

    def get_object(self, queryset=None):
        announcement = WelcomeAnnouncement.objects.first()
        if announcement:
            return announcement
        return WelcomeAnnouncement(created_by=self.request.user)

    def form_valid(self, form):
        form.instance.created_by = form.instance.created_by or self.request.user
        form.instance.full_clean()
        form.save()
        messages.success(self.request, "Welcome announcement saved.")
        return redirect(self.success_url)


class SystemSettingUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    template_name = "accounts/system_settings_form.html"
    form_class = SystemSettingForm
    success_url = reverse_lazy("dashboard")

    def test_func(self):
        return self.request.user.is_superuser or self.request.user.has_perm("accounts.manage_system_settings")

    def get_object(self, queryset=None):
        return SystemSetting.current()

    def form_valid(self, form):
        messages.success(self.request, "System settings saved.")
        return super().form_valid(form)


@require_POST
def mark_announcement_seen(request, pk):
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False}, status=403)
    announcement = WelcomeAnnouncement.objects.filter(pk=pk).first()
    if not announcement:
        return JsonResponse({"ok": False}, status=404)
    if not request.session.session_key:
        request.session.save()
    AnnouncementSeen.objects.get_or_create(announcement=announcement, user=request.user, session_key=request.session.session_key or "")
    return JsonResponse({"ok": True})


@require_POST
def announcement_image_upload(request):
    if not (request.user.is_superuser or request.user.has_perm("accounts.manage_welcome_announcement")):
        return JsonResponse({"error": "Permission denied."}, status=403)
    uploaded = request.FILES.get("file")
    if not uploaded or uploaded.size > 5 * 1024 * 1024:
        return JsonResponse({"error": "Upload an image smaller than 5 MB."}, status=400)
    try:
        image = Image.open(uploaded)
        image.verify()
        uploaded.seek(0)
    except Exception:
        return JsonResponse({"error": "Upload a valid image file."}, status=400)
    saved_name = default_storage.save(f"announcements/editor/{uploaded.name}", uploaded)
    return JsonResponse({"location": default_storage.url(saved_name)})


class AdminUserCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    template_name = 'accounts/user_create.html'
    form_class = AdminUserCreateForm
    success_url = reverse_lazy('accounts:user_list')

    def test_func(self):
        return self.request.user.is_superuser

    def handle_no_permission(self):
        messages.error(self.request, 'Only admin can create users.')
        return super().handle_no_permission()

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"User '{self.object.username}' created successfully.")
        return response


class AdminUserListView(LoginRequiredMixin, UserPassesTestMixin, ListView):
    template_name = "accounts/user_list.html"
    context_object_name = "users"
    paginate_by = 25

    def test_func(self):
        return self.request.user.is_superuser

    def handle_no_permission(self):
        messages.error(self.request, "Only admin can manage users.")
        return super().handle_no_permission()

    def get_queryset(self):
        UserModel = get_user_model()
        qs = UserModel.objects.all().order_by("username")
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(username__icontains=q)
                | Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
                | Q(email__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = (self.request.GET.get("q") or "").strip()
        return context


class UserActivityListView(LoginRequiredMixin, UserPassesTestMixin, ListView):
    template_name = "accounts/user_activity_list.html"
    context_object_name = "activities"
    paginate_by = 50

    def test_func(self):
        return self.request.user.is_superuser or self.request.user.has_perm("accounts.view_user_activity")

    def handle_no_permission(self):
        messages.error(self.request, "You do not have permission to view user activity.")
        return super().handle_no_permission()

    def get_queryset(self):
        queryset = UserActivity.objects.select_related("user").all()
        search_by = (self.request.GET.get("search_by") or "who").strip()
        query = (self.request.GET.get("q") or "").strip()
        filters = {
            "user": Q(user__username__icontains=query),
            "who": Q(user__username__icontains=query) | Q(user__first_name__icontains=query) | Q(user__last_name__icontains=query),
            "ip": Q(ip_address__icontains=query),
            "device": Q(user_agent__icontains=query) | Q(browser__icontains=query) | Q(device__icontains=query),
            "what": Q(path__icontains=query) | Q(activity__icontains=query),
        }
        if query and search_by in filters:
            queryset = queryset.filter(filters[search_by])
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_by"] = (self.request.GET.get("search_by") or "who").strip()
        context["query"] = (self.request.GET.get("q") or "").strip()
        return context


class AdminUserUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    template_name = "accounts/user_edit.html"
    form_class = AdminUserUpdateForm
    success_url = reverse_lazy("accounts:user_list")

    def test_func(self):
        return self.request.user.is_superuser

    def handle_no_permission(self):
        messages.error(self.request, "Only admin can manage users.")
        return super().handle_no_permission()

    def get_queryset(self):
        return get_user_model().objects.all()

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"User '{self.object.username}' updated.")
        return response


class AdminUserDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    template_name = "accounts/user_confirm_delete.html"
    success_url = reverse_lazy("accounts:user_list")

    def test_func(self):
        return self.request.user.is_superuser

    def handle_no_permission(self):
        messages.error(self.request, "Only admin can manage users.")
        return super().handle_no_permission()

    def get_queryset(self):
        return get_user_model().objects.all()

    def dispatch(self, request, *args, **kwargs):
        user_obj = self.get_object()
        if user_obj.pk == request.user.pk:
            messages.error(request, "You cannot delete your own account.")
            return redirect("accounts:user_list")
        if getattr(user_obj, "is_superuser", False):
            messages.error(request, "You cannot delete a superuser account.")
            return redirect("accounts:user_list")
        return super().dispatch(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        try:
            response = super().delete(request, *args, **kwargs)
        except ProtectedError:
            messages.error(
                request,
                "Cannot delete this user because it is referenced by bookings/reports. Deactivate the user instead.",
            )
            return redirect("accounts:user_edit", pk=self.object.pk)
        messages.success(request, f"User '{self.object.username}' deleted.")
        return response
