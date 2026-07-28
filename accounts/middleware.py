from __future__ import annotations

import ipaddress

from django.db import DatabaseError, OperationalError, ProgrammingError
from django.urls import Resolver404, resolve

from .models import UserActivity


def _browser_and_device(user_agent: str) -> tuple[str, str]:
    agent = (user_agent or "").lower()
    if "edg/" in agent:
        browser = "Microsoft Edge"
    elif "opr/" in agent or "opera" in agent:
        browser = "Opera"
    elif "firefox/" in agent:
        browser = "Firefox"
    elif "chrome/" in agent or "crios/" in agent:
        browser = "Chrome"
    elif "safari/" in agent:
        browser = "Safari"
    else:
        browser = "Unknown browser"

    if "ipad" in agent or "tablet" in agent:
        device = "Tablet"
    elif "mobile" in agent or "android" in agent or "iphone" in agent:
        device = "Mobile"
    else:
        device = "Desktop"
    return browser, device


def _activity_label(request) -> str:
    try:
        match = resolve(request.path_info)
        view_name = (match.view_name or request.path.strip("/") or "Dashboard").replace(":", " / ").replace("_", " ")
    except Resolver404:
        view_name = request.path.strip("/") or "Dashboard"
    verb = "Viewed" if request.method == "GET" else "Performed"
    return f"{verb} {view_name.title()}"[:255]


class UserActivityMiddleware:
    """Store successful and failed authenticated application requests for auditing."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, "user", None)
        if not getattr(user, "is_authenticated", False):
            return response
        if request.path.startswith("/static/") or request.path.startswith("/media/"):
            return response

        browser, device = _browser_and_device(request.META.get("HTTP_USER_AGENT", ""))
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
        ip_address = (forwarded_for.split(",")[0].strip() if forwarded_for else request.META.get("REMOTE_ADDR")) or None
        try:
            ip_address = str(ipaddress.ip_address(ip_address)) if ip_address else None
        except ValueError:
            ip_address = None
        try:
            UserActivity.objects.create(
                user=user,
                activity=_activity_label(request),
                method=request.method,
                path=request.path[:500],
                status_code=response.status_code,
                browser=browser,
                device=device,
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:1000],
                ip_address=ip_address,
            )
        except (OperationalError, ProgrammingError, DatabaseError):
            # Keep the application available while a deployment migration is pending.
            pass
        return response
