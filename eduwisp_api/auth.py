# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Michele Salerno e i contributori di EduWISP
"""Autenticazione con il token dell'app e regole di sola lettura (ADR-0022)."""

from django.conf import settings
from django.utils import timezone
from eduwisp_devices.secrets import check_secret
from rest_framework import authentication, exceptions, permissions

from .models import AppToken


class AppTokenAuthentication(authentication.BaseAuthentication):
    """``Authorization: Bearer <id>.<segreto>``."""

    def authenticate(self, request):
        intestazione = request.headers.get("Authorization", "")
        schema, _, credenziale = intestazione.partition(" ")
        if schema != "Bearer" or not credenziale:
            return None
        ident, _, segreto = credenziale.partition(".")
        try:
            token = AppToken.objects.select_related("user").get(pk=int(ident))
        except (ValueError, AppToken.DoesNotExist):
            raise exceptions.AuthenticationFailed("Credenziale non valida.") from None
        if (
            not token.is_valid
            or not token.user.is_active
            or not check_secret(segreto, token.secret_hash)
        ):
            raise exceptions.AuthenticationFailed("Credenziale non valida o scaduta.")
        AppToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
        return token.user, token

    def authenticate_header(self, request):
        return "Bearer"


def is_read_only_account(user):
    """Stesso gruppo del portale (per esempio l'utente «demo» dell'ambiente di prova)."""
    gruppo = getattr(settings, "EDUWISP_READ_ONLY_GROUP", "sola-lettura")
    return user.is_authenticated and user.groups.filter(name=gruppo).exists()


class SolaLettura(permissions.BasePermission):
    """Account in sola lettura e «vedi come»: nessuna modifica."""

    message = "Sola lettura: nessuna modifica è possibile."

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS or getattr(view, "sempre_permessa", False):
            return True
        token = request.auth
        if token is not None and token.view_as_id:
            return False
        return not is_read_only_account(request.user)
