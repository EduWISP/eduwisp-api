# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Michele Salerno e i contributori di EduWISP
"""Token delle app mobili (ADR-0022): uno per telefono, con scadenza, revocabile."""

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from eduwisp_devices.secrets import hash_secret, new_secret
from eduwisp_users.models import Membership

DURATA = timedelta(days=30)


class AppToken(models.Model):
    """Credenziale di un'app su un telefono. Il server conserva solo l'impronta del segreto."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="app_tokens",
        verbose_name="utente",
    )
    label = models.CharField("telefono", max_length=100, blank=True)
    secret_hash = models.CharField(max_length=64, editable=False)
    created_at = models.DateTimeField("creato il", auto_now_add=True)
    last_used_at = models.DateTimeField("ultimo uso", null=True, blank=True)
    expires_at = models.DateTimeField("scade il")
    revoked = models.BooleanField("revocato", default=False)
    view_as = models.ForeignKey(
        Membership,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="«vedi come» attivo",
    )
    view_as_started_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "token di un'app"
        verbose_name_plural = "token delle app"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} — {self.label or 'telefono'}"

    @classmethod
    def issue(cls, user, label=""):
        """Crea il token e restituisce (token, credenziale da consegnare all'app una volta)."""
        segreto = new_secret()
        token = cls.objects.create(
            user=user,
            label=label[:100],
            secret_hash=hash_secret(segreto),
            expires_at=timezone.now() + DURATA,
        )
        return token, f"{token.pk}.{segreto}"

    @property
    def is_valid(self):
        return not self.revoked and timezone.now() < self.expires_at
