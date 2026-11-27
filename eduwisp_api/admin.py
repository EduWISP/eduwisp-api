# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Michele Salerno e i contributori di EduWISP
from django.contrib import admin

from .models import AppToken


@admin.register(AppToken)
class AppTokenAdmin(admin.ModelAdmin):
    """Telefoni collegati: l'amministratore di sistema può revocarli."""

    list_display = ["user", "label", "created_at", "last_used_at", "expires_at", "revoked"]
    list_filter = ["revoked"]
    readonly_fields = ["user", "label", "created_at", "last_used_at", "expires_at", "view_as"]
    fields = readonly_fields + ["revoked"]

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    has_view_permission = lambda self, request, obj=None: request.user.is_superuser  # noqa: E731
    has_change_permission = lambda self, request, obj=None: request.user.is_superuser  # noqa: E731

    def has_add_permission(self, request):
        return False
