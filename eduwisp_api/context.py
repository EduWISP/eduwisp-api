# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Michele Salerno e i contributori di EduWISP
"""Chi guarda, con quale ruolo e quale menu (ADR-0018, ADR-0022)."""

from dataclasses import dataclass, field

from eduwisp_school.models import AssignmentKind, SchoolClass, TeachingAssignment
from eduwisp_users.models import Membership, Role

RUOLI = {
    Role.SCHOOL_ADMIN: "Dirigente",
    Role.TEACHER: "Docente",
    Role.GUARDIAN: "Famiglia",
}
PRIORITA = [Role.SCHOOL_ADMIN, Role.TEACHER, Role.GUARDIAN]


@dataclass
class Contesto:
    viewer: object
    user: object
    membership: Membership | None
    vedi_come: bool = False
    coordinate: list = field(default_factory=list)

    @property
    def role(self):
        return self.membership.role if self.membership else None

    @property
    def organization(self):
        return self.membership.organization if self.membership else None


def appartenenze(user):
    return list(
        Membership.objects.select_related("organization")
        .filter(user=user, role__in=PRIORITA, organization__is_active=True)
        .order_by("organization__name")
    )


def classi_coordinate(user, organization):
    """Classi di cui la persona è coordinatrice nell'anno in corso."""
    ids = TeachingAssignment.objects.filter(
        teacher=user,
        organization=organization,
        kind=AssignmentKind.COORDINATORE,
        school_year__is_current=True,
        school_class__isnull=False,
    ).values_list("school_class_id", flat=True)
    return list(SchoolClass.objects.filter(pk__in=ids).select_related("section"))


def contesto(request):
    token = request.auth
    if token is not None and token.view_as_id and request.user.is_superuser:
        m = Membership.objects.select_related("user", "organization").get(pk=token.view_as_id)
        ctx = Contesto(request.user, m.user, m, vedi_come=True)
    else:
        elenco = appartenenze(request.user)
        scelta = request.query_params.get("membership")
        m = next((x for x in elenco if str(x.pk) == scelta), None)
        if m is None and elenco:
            m = sorted(elenco, key=lambda x: PRIORITA.index(x.role))[0]
        ctx = Contesto(request.user, request.user, m)
    if ctx.role == Role.TEACHER:
        ctx.coordinate = classi_coordinate(ctx.user, ctx.organization)
    return ctx


def menu(ctx):
    """Voci del menu dell'app, decise dal server secondo il ruolo."""
    if ctx.role == Role.SCHOOL_ADMIN:
        voci = [("istituto", "Istituto"), ("classi", "Classi"), ("richieste", "Richieste di app")]
    elif ctx.role == Role.TEACHER:
        voci = [("classi", "Le mie classi"), ("richieste", "Richieste di app")]
        if ctx.coordinate:
            voci.insert(1, ("coordinamento", "Coordinamento"))
    elif ctx.role == Role.GUARDIAN:
        voci = [("figli", "I miei figli"), ("richieste", "Richieste di app")]
    else:
        voci = []
    return [{"id": i, "titolo": t} for i, t in voci]
