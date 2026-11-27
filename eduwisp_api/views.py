# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Michele Salerno e i contributori di EduWISP
"""API JSON per le app mobili (ADR-0022): stessi permessi del portale."""

from datetime import timedelta

from django.contrib.auth import authenticate
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q
from django.http import Http404
from django.utils import timezone
from eduwisp_apps.models import (
    App,
    AppRequest,
    PlatformApp,
    PlatformStatus,
    RequestStatus,
    TemporaryUnlock,
)
from eduwisp_apps.requests import (
    add_opinion,
    can_decide,
    can_give_opinion,
    decide,
    visible_requests,
)
from eduwisp_apps.unlocks import (
    DURATE_MINUTI,
    active_unlocks,
    allowed_apps_for_class,
    end_unlock,
    unlock,
    unlockable_apps,
)
from eduwisp_audit.log import record
from eduwisp_audit.models import Action
from eduwisp_devices.models import DeviceAssignment
from eduwisp_school.models import SchoolClass, Student, StudentEnrollment
from eduwisp_school.queries import classes_for_teacher, linked_students, students_for_guardian
from eduwisp_users.models import Membership, Role
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .auth import AppTokenAuthentication, SolaLettura, is_read_only_account
from .context import RUOLI, appartenenze, contesto, menu
from .models import AppToken

ORE_SENZA_CONTATTO = 24


class Base(APIView):
    authentication_classes = [AppTokenAuthentication]
    permission_classes = [IsAuthenticated, SolaLettura]

    def finalize_response(self, request, response, *args, **kwargs):
        risposta = super().finalize_response(request, response, *args, **kwargs)
        risposta["Cache-Control"] = "no-store"  # dati di minori: niente copie nelle cache
        return risposta

    def handle_exception(self, exc):
        if isinstance(exc, Http404):
            return Response({"errore": "Non trovato."}, status=404)
        if isinstance(exc, ValidationError):
            return Response({"errore": " ".join(exc.messages)}, status=400)
        if isinstance(exc, PermissionDenied):
            return Response({"errore": str(exc) or "Operazione non consentita."}, status=403)
        return super().handle_exception(exc)


def fuori_ambito(ctx, cosa):
    record(
        Action.ACCESS_DENIED,
        actor=ctx.viewer,
        organization=ctx.organization,
        subject=ctx.user if ctx.vedi_come else None,
        risorsa=cosa,
        app=True,
    )
    raise Http404


def stato_dispositivo(d):
    if d is None:
        return None
    limite = timezone.now() - timedelta(hours=ORE_SENZA_CONTATTO)
    return {
        "nome": d.display_name,
        "conforme": d.compliant,
        "ultimo_contatto": d.last_seen_at.isoformat() if d.last_seen_at else None,
        "senza_contatto": d.last_seen_at is None or d.last_seen_at < limite,
    }


def icona(request, app):
    f = getattr(app, "icon", None)
    return request.build_absolute_uri(f.url) if f else None


# Accesso -----------------------------------------------------------------------------------


class Accedi(APIView):
    """Utente e password dell'istituto → token per questo telefono."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        user = authenticate(
            request,
            username=str(request.data.get("username", ""))[:150],
            password=str(request.data.get("password", "")),
        )
        if user is None or not user.is_active:
            return Response({"errore": "Nome utente o password non corretti."}, status=401)
        token, credenziale = AppToken.issue(user, str(request.data.get("telefono", "")))
        return Response(
            {"token": credenziale, "scade": token.expires_at.isoformat()},
            status=status.HTTP_201_CREATED,
        )


class Esci(Base):
    sempre_permessa = True

    def post(self, request):
        token = request.auth
        if token.view_as_id:
            chiudi_vedi_come(token, request.user)
        token.revoked = True
        token.save(update_fields=["revoked"])
        return Response(status=204)


class Io(Base):
    def get(self, request):
        ctx = contesto(request)
        return Response(
            {
                "utente": {
                    "nome": ctx.viewer.get_full_name() or ctx.viewer.get_username(),
                    "amministratore": ctx.viewer.is_superuser,
                    "sola_lettura": is_read_only_account(ctx.viewer) or ctx.vedi_come,
                },
                "vedi_come": {
                    "persona": ctx.user.get_full_name() or ctx.user.get_username(),
                    "ruolo": RUOLI.get(ctx.role, ""),
                    "istituto": str(ctx.organization),
                }
                if ctx.vedi_come
                else None,
                "ruoli": [
                    {
                        "id": m.pk,
                        "ruolo": m.role,
                        "nome": RUOLI[m.role],
                        "istituto": str(m.organization),
                    }
                    for m in ([] if ctx.vedi_come else appartenenze(ctx.viewer))
                ],
                "ruolo_attuale": ctx.membership.pk if ctx.membership else None,
                "coordinatore_di": [str(c) for c in ctx.coordinate],
                "menu": menu(ctx),
            }
        )


# «Vedi come» dell'amministratore (sola lettura, registrato) ---------------------------------


def chiudi_vedi_come(token, user):
    m = token.view_as
    durata = (
        int((timezone.now() - token.view_as_started_at).total_seconds())
        if token.view_as_started_at
        else 0
    )
    record(
        Action.VIEW_AS_STOP,
        actor=user,
        organization=m.organization if m else None,
        subject=m.user if m else None,
        durata_secondi=durata,
        app=True,
    )
    token.view_as = None
    token.view_as_started_at = None
    token.save(update_fields=["view_as", "view_as_started_at"])


class VediCome(Base):
    sempre_permessa = True  # come nel portale: il «vedi come» è a sua volta in sola lettura

    def get(self, request):
        if not request.user.is_superuser:
            raise Http404
        ruolo = request.query_params.get("ruolo", Role.SCHOOL_ADMIN)
        if ruolo not in RUOLI:
            raise Http404
        persone = Membership.objects.select_related("user", "organization").filter(
            role=ruolo, organization__is_active=True
        )
        cerca = request.query_params.get("cerca", "").strip()
        if cerca:
            persone = persone.filter(
                Q(user__first_name__icontains=cerca) | Q(user__last_name__icontains=cerca)
            )
        return Response(
            [
                {
                    "id": m.pk,
                    "persona": m.user.get_full_name() or m.user.get_username(),
                    "istituto": str(m.organization),
                }
                for m in persone.order_by("user__last_name", "user__first_name")[:200]
            ]
        )

    def post(self, request):
        if not request.user.is_superuser:
            raise Http404
        m = Membership.objects.filter(pk=request.data.get("ruolo"), role__in=list(RUOLI)).first()
        if m is None:
            raise Http404
        token = request.auth
        if token.view_as_id:
            chiudi_vedi_come(token, request.user)
        token.view_as = m
        token.view_as_started_at = timezone.now()
        token.save(update_fields=["view_as", "view_as_started_at"])
        record(
            Action.VIEW_AS_START,
            actor=request.user,
            organization=m.organization,
            subject=m.user,
            reason=str(request.data.get("motivo", ""))[:200],
            ruolo=m.role,
            app=True,
        )
        return Response(status=204)

    def delete(self, request):
        if request.auth.view_as_id:
            chiudi_vedi_come(request.auth, request.user)
        return Response(status=204)


# Classi ------------------------------------------------------------------------------------


def classi_visibili(ctx):
    if ctx.role == Role.SCHOOL_ADMIN:
        return SchoolClass.objects.filter(
            organization=ctx.organization, school_year__is_current=True
        )
    if ctx.role == Role.TEACHER:
        return classes_for_teacher(ctx.user).filter(organization=ctx.organization)
    return SchoolClass.objects.none()


class Classi(Base):
    def get(self, request):
        ctx = contesto(request)
        classi = list(
            classi_visibili(ctx)
            .select_related("section__track")
            .order_by("section__name", "year_number")
        )
        studenti = dict(
            StudentEnrollment.objects.filter(school_class__in=classi)
            .values_list("school_class")
            .annotate(n=Count("id"))
        )
        limite = timezone.now() - timedelta(hours=ORE_SENZA_CONTATTO)
        disp = {
            r["school_class"]: r
            for r in DeviceAssignment.objects.filter(school_class__in=classi, ended_at__isnull=True)
            .values("school_class")
            .annotate(
                totale=Count("id"),
                non_conformi=Count("id", filter=Q(device__compliant=False)),
                senza_contatto=Count(
                    "id",
                    filter=Q(device__last_seen_at__lt=limite)
                    | Q(device__last_seen_at__isnull=True),
                ),
            )
        }
        coordinate = {c.pk for c in ctx.coordinate}
        if request.query_params.get("solo") == "coordinate":
            classi = [c for c in classi if c.pk in coordinate]
        return Response(
            [
                {
                    "id": c.pk,
                    "nome": str(c),
                    "indirizzo": str(c.section.track) if c.section.track_id else "",
                    "studenti": studenti.get(c.pk, 0),
                    "dispositivi": disp.get(c.pk, {}).get("totale", 0),
                    "non_conformi": disp.get(c.pk, {}).get("non_conformi", 0),
                    "senza_contatto": disp.get(c.pk, {}).get("senza_contatto", 0),
                    "coordinata": c.pk in coordinate,
                }
                for c in classi
            ]
        )


def classe_consentita(ctx, pk):
    c = classi_visibili(ctx).select_related("section", "school_year").filter(pk=pk).first()
    if c is None:
        fuori_ambito(ctx, f"classe {pk}")
    return c


class Classe(Base):
    def get(self, request, pk):
        ctx = contesto(request)
        c = classe_consentita(ctx, pk)
        assegnazioni = list(
            DeviceAssignment.objects.filter(school_class=c, ended_at__isnull=True).select_related(
                "device", "student"
            )
        )
        personali = {a.student_id: a.device for a in assegnazioni if a.student_id}
        studenti = Student.objects.filter(enrollments__school_class=c).order_by("display_name")
        return Response(
            {
                "id": c.pk,
                "nome": str(c),
                "anno_scolastico": c.school_year.label,
                "studenti": [
                    {
                        "id": s.pk,
                        "nome": s.display_name,
                        "tablet": stato_dispositivo(personali.get(s.pk)),
                    }
                    for s in studenti
                ],
                "tablet_condivisi": [
                    stato_dispositivo(a.device) for a in assegnazioni if not a.student_id
                ],
                "app_consentite": [
                    {"nome": a.name, "icona": icona(request, a)} for a in allowed_apps_for_class(c)
                ],
                "sblocchi": [
                    {
                        "id": s.pk,
                        "app": s.app.name,
                        "fino_alle": s.ends_at.isoformat(),
                        "da": s.teacher.get_full_name() if s.teacher else "",
                    }
                    for s in active_unlocks(c)
                ],
                "app_sbloccabili": [
                    {"id": a.pk, "nome": a.name} for a in unlockable_apps(c).order_by("name")
                ]
                if ctx.role == Role.TEACHER
                else [],
                "durate_minuti": list(DURATE_MINUTI) if ctx.role == Role.TEACHER else [],
            }
        )


class Sblocca(Base):
    def post(self, request, pk):
        ctx = contesto(request)
        if ctx.role != Role.TEACHER:
            raise Http404
        c = classe_consentita(ctx, pk)
        app = unlockable_apps(c).filter(pk=request.data.get("app") or 0).first()
        try:
            minuti = int(request.data.get("minuti", 0))
        except (TypeError, ValueError):
            minuti = 0
        if app is None or minuti not in DURATE_MINUTI:
            return Response({"errore": "Scegli un'app e una durata."}, status=400)
        s = unlock(ctx.user, c, app, minuti)
        return Response({"id": s.pk, "fino_alle": s.ends_at.isoformat()}, status=201)


class TerminaSblocco(Base):
    def post(self, request, pk):
        ctx = contesto(request)
        if ctx.role != Role.TEACHER:
            raise Http404
        s = TemporaryUnlock.objects.filter(pk=pk, organization=ctx.organization).first()
        if s is None:
            fuori_ambito(ctx, f"sblocco {pk}")
        classe_consentita(ctx, s.school_class_id)
        end_unlock(ctx.user, s)
        return Response(status=204)


# Richieste di app (ADR-0021) ----------------------------------------------------------------


def richiesta_json(request, ctx, r, dettaglio=False):
    dati = {
        "id": r.pk,
        "app": r.name or r.identifier,
        "identificativo": r.identifier,
        "studente": r.student.display_name,
        "classe": str(r.school_class) if r.school_class else "",
        "chiesta_il": r.created_at.isoformat(),
        "stato": r.status,
        "pareri": r.opinions.count(),
    }
    if dettaglio:
        dati |= {
            "motivazione_studente": r.note,
            "pareri_famiglia": [
                {
                    "da": p.guardian.get_full_name() or p.guardian.get_username(),
                    "motivo": p.reason,
                    "il": p.created_at.isoformat(),
                }
                for p in r.opinions.select_related("guardian")
            ],
            "decisione": {
                "da": r.decided_by.get_full_name() if r.decided_by else "",
                "il": r.decided_at.isoformat() if r.decided_at else None,
                "motivo": r.decision_reason,
            }
            if r.status != RequestStatus.IN_ATTESA
            else None,
            "puo_decidere": ctx.role == Role.TEACHER and can_decide(ctx.user, r),
            "puo_dare_parere": ctx.role == Role.GUARDIAN and can_give_opinion(ctx.user, r),
        }
    return dati


def richieste_visibili(ctx):
    if ctx.role not in RUOLI:
        return AppRequest.objects.none()
    return visible_requests(ctx.user, ctx.role, ctx.organization)


class Richieste(Base):
    def get(self, request):
        ctx = contesto(request)
        qs = richieste_visibili(ctx)
        stato = request.query_params.get("stato")
        if stato in RequestStatus.values:
            qs = qs.filter(status=stato)
        if request.query_params.get("solo") == "coordinate":
            qs = qs.filter(school_class__in=ctx.coordinate)
        return Response([richiesta_json(request, ctx, r) for r in qs.order_by("-created_at")[:200]])


def richiesta_consentita(ctx, pk):
    r = richieste_visibili(ctx).filter(pk=pk).first()
    if r is None:
        fuori_ambito(ctx, f"richiesta di app {pk}")
    return r


class Richiesta(Base):
    def get(self, request, pk):
        ctx = contesto(request)
        return Response(richiesta_json(request, ctx, richiesta_consentita(ctx, pk), dettaglio=True))


class Decisione(Base):
    def post(self, request, pk):
        ctx = contesto(request)
        if ctx.role != Role.TEACHER:
            raise PermissionDenied("Decide un docente della classe.")
        r = richiesta_consentita(ctx, pk)
        decide(ctx.user, r, bool(request.data.get("approva")), str(request.data.get("motivo", "")))
        return Response(richiesta_json(request, ctx, r, dettaglio=True))


class Parere(Base):
    def post(self, request, pk):
        ctx = contesto(request)
        if ctx.role != Role.GUARDIAN:
            raise PermissionDenied("Il parere lo danno i familiari.")
        r = richiesta_consentita(ctx, pk)
        add_opinion(ctx.user, r, str(request.data.get("motivo", "")))
        return Response(richiesta_json(request, ctx, r, dettaglio=True))


class Riepilogo(Base):
    """Per il controllo periodico dell'app (nessun servizio di notifica proprietario)."""

    def get(self, request):
        ctx = contesto(request)
        in_attesa = richieste_visibili(ctx).filter(status=RequestStatus.IN_ATTESA)
        dati = {"richieste_in_attesa": in_attesa.count()}
        if ctx.role == Role.GUARDIAN:
            # Per l'app della famiglia: le richieste su cui non ha ancora dato un parere
            dati["pareri_da_dare"] = in_attesa.exclude(opinions__guardian=ctx.user).count()
        return Response(dati)


def figli_visibili(ctx):
    if ctx.role != Role.GUARDIAN:
        raise Http404
    return students_for_guardian(ctx.user).filter(organization=ctx.organization)


def classe_attuale(studente):
    iscrizione = (
        StudentEnrollment.objects.filter(
            student=studente, school_class__school_year__is_current=True
        )
        .select_related("school_class__section", "school_class__school_year")
        .first()
    )
    return iscrizione.school_class if iscrizione else None


class Figli(Base):
    """Per l'app della famiglia (ADR-0018): solo i propri figli."""

    def get(self, request):
        ctx = contesto(request)
        figli = figli_visibili(ctx).order_by("display_name")
        risultato = []
        for f in figli:
            iscrizione = (
                StudentEnrollment.objects.filter(
                    student=f, school_class__school_year__is_current=True
                )
                .select_related("school_class")
                .first()
            )
            tablet = [
                stato_dispositivo(a.device)
                for a in DeviceAssignment.objects.filter(
                    student=f, ended_at__isnull=True
                ).select_related("device")
            ]
            risultato.append(
                {
                    "id": f.pk,
                    "nome": f.display_name,
                    "classe": str(iscrizione.school_class) if iscrizione else "",
                    "tablet": tablet,
                    "maggiorenne_senza_consenso": False,
                }
            )
        # Maggiorenni senza consenso (ADR-0018): solo il nome e il fatto, nessun dato
        visibili = {f["id"] for f in risultato}
        for f in linked_students(ctx.user).filter(organization=ctx.organization):
            if f.pk not in visibili:
                risultato.append(
                    {
                        "id": f.pk,
                        "nome": f.display_name,
                        "classe": "",
                        "tablet": [],
                        "maggiorenne_senza_consenso": True,
                    }
                )
        return Response(sorted(risultato, key=lambda f: f["nome"]))


class Figlio(Base):
    """Dettaglio di un figlio per l'app della famiglia: tablet, app consentite, richieste."""

    def get(self, request, pk):
        ctx = contesto(request)
        f = figli_visibili(ctx).filter(pk=pk).first()
        if f is None:
            fuori_ambito(ctx, f"studente {pk}")
        classe = classe_attuale(f)
        vietate = PlatformApp.objects.filter(status=PlatformStatus.VIETATA).values_list(
            "identifier", flat=True
        )
        personali = (
            App.objects.filter(rules__student=f, organization=ctx.organization)
            .exclude(identifier__in=vietate)
            .distinct()
        )
        app = [
            {"nome": a.name, "icona": icona(request, a), "solo_per_lui": False}
            for a in (allowed_apps_for_class(classe) if classe else [])
        ]
        app += [
            {"nome": a.name, "icona": icona(request, a), "solo_per_lui": True}
            for a in personali.order_by("name")
        ]
        tablet = [
            stato_dispositivo(a.device)
            for a in DeviceAssignment.objects.filter(
                student=f, ended_at__isnull=True
            ).select_related("device")
        ]
        richieste = richieste_visibili(ctx).filter(student=f).order_by("-created_at")[:100]
        return Response(
            {
                "id": f.pk,
                "nome": f.display_name,
                "classe": str(classe) if classe else "",
                "anno_scolastico": classe.school_year.label if classe else "",
                "tablet": tablet,
                "app_consentite": app,
                "sblocchi": [
                    {"app": s.app.name, "fino_alle": s.ends_at.isoformat()}
                    for s in (active_unlocks(classe) if classe else [])
                ],
                "richieste": [richiesta_json(request, ctx, r) for r in richieste],
            }
        )
