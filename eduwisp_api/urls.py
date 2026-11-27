# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Michele Salerno e i contributori di EduWISP
"""Da includere nel progetto: path("", include("eduwisp_api.urls"))."""

from django.urls import path

from . import views

app_name = "eduwisp_api"

P = "api/app/v1/"
urlpatterns = [
    path(P + "accedi", views.Accedi.as_view(), name="accedi"),
    path(P + "esci", views.Esci.as_view(), name="esci"),
    path(P + "io", views.Io.as_view(), name="io"),
    path(P + "vedi-come", views.VediCome.as_view(), name="vedi_come"),
    path(P + "classi", views.Classi.as_view(), name="classi"),
    path(P + "classi/<int:pk>", views.Classe.as_view(), name="classe"),
    path(P + "classi/<int:pk>/sblocchi", views.Sblocca.as_view(), name="sblocca"),
    path(P + "sblocchi/<int:pk>/termina", views.TerminaSblocco.as_view(), name="termina_sblocco"),
    path(P + "richieste", views.Richieste.as_view(), name="richieste"),
    path(P + "richieste/<int:pk>", views.Richiesta.as_view(), name="richiesta"),
    path(P + "richieste/<int:pk>/decisione", views.Decisione.as_view(), name="decisione"),
    path(P + "richieste/<int:pk>/parere", views.Parere.as_view(), name="parere"),
    path(P + "riepilogo", views.Riepilogo.as_view(), name="riepilogo"),
    path(P + "figli", views.Figli.as_view(), name="figli"),
]
