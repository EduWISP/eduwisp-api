# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Michele Salerno e i contributori di EduWISP
from django.apps import AppConfig


class ApiConfig(AppConfig):
    name = "eduwisp_api"
    verbose_name = "API per le app mobili"
    default_auto_field = "django.db.models.BigAutoField"
