from django.urls import path

from .views import (
    AdminUserCreateView,
    AdminUserDeleteView,
    AdminUserListView,
    AdminUserUpdateView,
    UserActivityListView,
    UserLoginView,
    UserLogoutView,
)

app_name = 'accounts'

urlpatterns = [
    path('login/', UserLoginView.as_view(), name='login'),
    path('logout/', UserLogoutView.as_view(), name='logout'),
    path('users/', AdminUserListView.as_view(), name='user_list'),
    path('user-activity/', UserActivityListView.as_view(), name='user_activity'),
    path('users/new/', AdminUserCreateView.as_view(), name='create_user'),
    path('users/<int:pk>/edit/', AdminUserUpdateView.as_view(), name='user_edit'),
    path('users/<int:pk>/delete/', AdminUserDeleteView.as_view(), name='user_delete'),
]
