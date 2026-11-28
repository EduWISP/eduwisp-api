# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Michele Salerno e i contributori di EduWISP
import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from eduwisp_apps.models import App, AppRequest, AppRule, RequestStatus, TemporaryUnlock
from eduwisp_audit.models import Action, AuditEvent
from eduwisp_school.models import AssignmentKind, TeachingAssignment
from rest_framework.test import APIClient

from eduwisp_api.models import AppToken

pytestmark = pytest.mark.django_db
V = "/api/app/v1/"
User = get_user_model()


@pytest.fixture
def richiesta(scuola):
    return AppRequest.objects.create(
        organization=scuola["org"],
        student=scuola["figlio"],
        school_class=scuola["c1a"],
        identifier="org.example.dizionario",
        name="Dizionario",
    )


def test_accesso_e_token(scuola):
    docente = scuola["docente"]
    docente.set_password("password-di-prova-123")
    docente.save()
    c = APIClient()
    assert c.post(V + "accedi", {"username": "docente", "password": "sbagliata"}).status_code == 401
    r = c.post(
        V + "accedi",
        {"username": "docente", "password": "password-di-prova-123", "telefono": "Pixel"},
    )
    assert r.status_code == 201
    token = r.json()["token"]
    t = AppToken.objects.get()
    assert token.split(".", 1)[1] not in t.secret_hash  # solo l'impronta sul server
    c.credentials(HTTP_AUTHORIZATION="Bearer " + token)
    assert c.get(V + "io").status_code == 200
    assert c.get(V + "io")["Cache-Control"] == "no-store"
    assert c.post(V + "esci").status_code == 204
    assert c.get(V + "io").status_code == 401


def test_senza_token(db):
    assert APIClient().get(V + "io").status_code == 401


def test_menu_per_ruolo(scuola, api_per):
    menu = lambda u: [v["id"] for v in api_per(u).get(V + "io").json()["menu"]]  # noqa: E731
    assert menu(scuola["preside"]) == ["istituto", "classi", "richieste"]
    assert menu(scuola["docente"]) == ["classi", "richieste"]
    assert menu(scuola["genitore"]) == ["figli", "richieste"]
    TeachingAssignment.objects.create(
        organization=scuola["org"],
        teacher=scuola["docente"],
        school_year=scuola["c1a"].school_year,
        section=scuola["c1a"].section,
        school_class=scuola["c1a"],
        kind=AssignmentKind.COORDINATORE,
    )
    assert menu(scuola["docente"]) == ["classi", "coordinamento", "richieste"]


def test_docente_vede_solo_le_sue_classi(scuola, api_per):
    api = api_per(scuola["docente"])
    ids = [c["id"] for c in api.get(V + "classi").json()]
    assert ids == [scuola["c1a"].pk]
    assert api.get(V + f"classi/{scuola['c1a'].pk}").json()["studenti"][0]["nome"] == "Rossi Anna"
    assert api.get(V + f"classi/{scuola['c1b'].pk}").status_code == 404
    assert AuditEvent.objects.filter(action=Action.ACCESS_DENIED).count() == 1
    preside = api_per(scuola["preside"])
    assert len(preside.get(V + "classi").json()) == 2


def test_sblocco_dal_telefono(scuola, api_per):
    app = App.objects.create(
        organization=scuola["org"], name="Enciclopedia", identifier="org.example.enc"
    )
    api = api_per(scuola["docente"])
    dettaglio = api.get(V + f"classi/{scuola['c1a'].pk}").json()
    assert {"id": app.pk, "nome": "Enciclopedia"} in dettaglio["app_sbloccabili"]
    r = api.post(
        V + f"classi/{scuola['c1a'].pk}/sblocchi", {"app": app.pk, "minuti": 60}, format="json"
    )
    assert r.status_code == 201
    s = TemporaryUnlock.objects.get()
    assert api.post(V + f"sblocchi/{s.pk}/termina").status_code == 204
    # Il dirigente vede ma non sblocca
    r = api_per(scuola["preside"]).post(
        V + f"classi/{scuola['c1a'].pk}/sblocchi", {"app": app.pk, "minuti": 60}
    )
    assert r.status_code == 404


def test_richieste_decisione_e_parere(scuola, api_per, richiesta):
    famiglia = api_per(scuola["genitore"])
    r = famiglia.post(
        V + f"richieste/{richiesta.pk}/parere", {"motivo": "Serve per latino"}, format="json"
    )
    assert r.status_code == 200 and r.json()["pareri_famiglia"][0]["motivo"] == "Serve per latino"
    assert r.json()["mio_parere"] == "Serve per latino"
    # Un secondo parere aggiorna il primo
    r = famiglia.post(
        V + f"richieste/{richiesta.pk}/parere",
        {"motivo": "Serve per latino e greco"},
        format="json",
    )
    assert [p["motivo"] for p in r.json()["pareri_famiglia"]] == ["Serve per latino e greco"]
    docente = api_per(scuola["docente"])
    assert docente.get(V + "riepilogo").json() == {"richieste_in_attesa": 1}
    r = docente.post(
        V + f"richieste/{richiesta.pk}/decisione", {"approva": True, "motivo": ""}, format="json"
    )
    assert r.status_code == 400
    r = docente.post(
        V + f"richieste/{richiesta.pk}/decisione",
        {"approva": True, "motivo": "Utile"},
        format="json",
    )
    assert r.status_code == 200 and r.json()["stato"] == RequestStatus.APPROVATA
    assert AppRule.objects.filter(student=scuola["figlio"]).exists()
    # Chi non è della classe non vede la richiesta
    estraneo = User.objects.create_user("estraneo")
    assert api_per(estraneo).get(V + f"richieste/{richiesta.pk}").status_code == 404


def test_famiglia_vede_solo_i_propri_figli(scuola, api_per):
    figli = api_per(scuola["genitore"]).get(V + "figli").json()
    assert [f["nome"] for f in figli] == ["Rossi Anna"]
    assert api_per(scuola["docente"]).get(V + "figli").status_code == 404


def test_dettaglio_del_figlio(scuola, api_per, richiesta):
    famiglia = api_per(scuola["genitore"])
    figlio = scuola["figlio"]
    app = App.objects.create(
        organization=scuola["org"], identifier="org.example.atlante", name="Atlante"
    )
    AppRule.objects.create(organization=scuola["org"], app=app, student=figlio)
    d = famiglia.get(V + f"figli/{figlio.pk}").json()
    assert d["nome"] == "Rossi Anna" and d["classe"]
    assert {"nome": "Atlante", "icona": None, "solo_per_lui": True} in d["app_consentite"]
    assert [r["app"] for r in d["richieste"]] == ["Dizionario"]
    # Il figlio di un'altra famiglia non si vede, e il tentativo è registrato
    assert famiglia.get(V + f"figli/{scuola['altro'].pk}").status_code == 404
    assert AuditEvent.objects.filter(action=Action.ACCESS_DENIED).exists()
    assert api_per(scuola["docente"]).get(V + f"figli/{figlio.pk}").status_code == 404


def test_figlio_maggiorenne_senza_consenso(scuola, api_per):
    from datetime import date

    figlio = scuola["figlio"]
    figlio.birth_date = date(1982, 1, 1)
    figlio.save()
    famiglia = api_per(scuola["genitore"])
    assert famiglia.get(V + "figli").json() == [
        {
            "id": figlio.pk,
            "nome": "Rossi Anna",
            "classe": "",
            "tablet": [],
            "maggiorenne_senza_consenso": True,
        }
    ]
    assert famiglia.get(V + f"figli/{figlio.pk}").status_code == 404
    figlio.family_access_granted = True
    figlio.save()
    assert famiglia.get(V + "figli").json()[0]["maggiorenne_senza_consenso"] is False


def test_pareri_da_dare(scuola, api_per, richiesta):
    famiglia = api_per(scuola["genitore"])
    assert famiglia.get(V + "riepilogo").json() == {"richieste_in_attesa": 1, "pareri_da_dare": 1}
    famiglia.post(V + f"richieste/{richiesta.pk}/parere", {"motivo": "Serve"}, format="json")
    assert famiglia.get(V + "riepilogo").json() == {"richieste_in_attesa": 1, "pareri_da_dare": 0}


def test_account_demo_in_sola_lettura_con_vedi_come(scuola, api_per, richiesta):
    demo = User.objects.create_superuser("demo", password="demo")
    demo.groups.add(Group.objects.create(name="sola-lettura"))
    c = APIClient()
    token = c.post(V + "accedi", {"username": "demo", "password": "demo"}).json()["token"]
    c.credentials(HTTP_AUTHORIZATION="Bearer " + token)
    assert c.get(V + "io").json()["utente"]["sola_lettura"] is True
    persone = c.get(V + "vedi-come", {"ruolo": "teacher"}).json()
    assert persone[0]["persona"] == "Docente"
    assert (
        c.post(V + "vedi-come", {"ruolo": scuola["m_docente"].pk}, format="json").status_code == 204
    )
    io = c.get(V + "io").json()
    assert io["vedi_come"]["ruolo"] == "Docente" and [v["id"] for v in io["menu"]] == [
        "classi",
        "richieste",
    ]
    # Nessuna modifica durante il «vedi come»
    r = c.post(
        V + f"richieste/{richiesta.pk}/decisione", {"approva": True, "motivo": "x"}, format="json"
    )
    assert r.status_code == 403
    assert c.delete(V + "vedi-come").status_code == 204
    azioni = list(AuditEvent.objects.values_list("action", flat=True))
    assert Action.VIEW_AS_START in azioni and Action.VIEW_AS_STOP in azioni


def test_vedi_come_solo_per_l_amministratore(scuola, api_per):
    api = api_per(scuola["preside"])
    assert api.get(V + "vedi-come").status_code == 404
    assert api.post(V + "vedi-come", {"ruolo": scuola["m_docente"].pk}).status_code == 404


def test_famiglia_isolata_da_altri_studenti_e_istituti(scuola, api_per, richiesta):
    """La famiglia vede rigorosamente solo i propri figli (ADR-0018): nessun altro studente
    dello stesso istituto, nessun altro istituto, nessuna classe."""
    from datetime import date

    from eduwisp_school.models import (
        Guardian,
        SchoolClass,
        SchoolLevel,
        SchoolYear,
        Section,
        Site,
        Student,
        StudentEnrollment,
    )
    from eduwisp_users.models import Membership, Organization, Role

    org, figlio, altro = scuola["org"], scuola["figlio"], scuola["altro"]
    # Compagno di classe del figlio, con la sua richiesta di app
    compagno = Student.objects.create(organization=org, display_name="Verdi Marco")
    StudentEnrollment.objects.create(organization=org, student=compagno, school_class=scuola["c1a"])
    r_compagno = AppRequest.objects.create(
        organization=org, student=compagno, school_class=scuola["c1a"], identifier="org.x.c"
    )
    r_altro = AppRequest.objects.create(
        organization=org, student=altro, school_class=scuola["c1b"], identifier="org.x.a"
    )
    # Un altro istituto, con uno studente e una richiesta
    org2 = Organization.objects.create(name="Istituto Altro", slug="altro")
    sede = Site.objects.create(organization=org2, name="Sede", level=SchoolLevel.PRIMARIA)
    anno = SchoolYear.objects.create(
        organization=org2,
        label="2026/2027",
        start_date=date(2026, 9, 1),
        end_date=date(2027, 6, 30),
        is_current=True,
    )
    sez = Section.objects.create(organization=org2, site=sede, name="C")
    c2 = SchoolClass.objects.create(organization=org2, school_year=anno, section=sez, year_number=1)
    estraneo = Student.objects.create(organization=org2, display_name="Neri Sara")
    StudentEnrollment.objects.create(organization=org2, student=estraneo, school_class=c2)
    r_org2 = AppRequest.objects.create(
        organization=org2, student=estraneo, school_class=c2, identifier="org.x.e"
    )
    m_org2 = Membership.objects.create(
        user=User.objects.create_user("altro-genitore"), organization=org2, role=Role.GUARDIAN
    )
    Guardian.objects.create(organization=org2, user=m_org2.user, student=estraneo)

    famiglia = api_per(scuola["genitore"])
    io = famiglia.get(V + "io").json()
    assert [r["istituto"] for r in io["ruoli"]] == ["Liceo Fittizio"]
    # Un ruolo di un'altra persona passato come parametro non cambia nulla
    for q in (f"?membership={m_org2.pk}", f"?membership={scuola['m_docente'].pk}", ""):
        assert [f["id"] for f in famiglia.get(V + "figli" + q).json()] == [figlio.pk]
        assert [r["id"] for r in famiglia.get(V + "richieste" + q).json()] == [richiesta.pk]
        assert famiglia.get(V + "classi" + q).json() == []
    for s in (compagno, altro, estraneo):
        assert famiglia.get(V + f"figli/{s.pk}").status_code == 404
    for r in (r_compagno, r_altro, r_org2):
        assert famiglia.get(V + f"richieste/{r.pk}").status_code == 404
        assert (
            famiglia.post(V + f"richieste/{r.pk}/parere", {"motivo": "x"}, format="json")
        ).status_code == 404
    for c in (scuola["c1a"], scuola["c1b"], c2):
        assert famiglia.get(V + f"classi/{c.pk}").status_code == 404
    assert famiglia.get(V + "vedi-come").status_code == 404
    assert famiglia.get(V + "riepilogo").json()["richieste_in_attesa"] == 1
    # Nel dettaglio del figlio non compare nessun compagno
    d = famiglia.get(V + f"figli/{figlio.pk}").json()
    assert "Verdi Marco" not in str(d) and [r["id"] for r in d["richieste"]] == [richiesta.pk]
    # Ogni tentativo fuori ambito è registrato
    assert AuditEvent.objects.filter(action=Action.ACCESS_DENIED).count() >= 9
    # Collegamento disattivato o figlio non più iscritto: non si vede più nulla
    Guardian.objects.filter(user=scuola["genitore"]).update(is_active=False)
    assert famiglia.get(V + "figli").json() == []
    assert famiglia.get(V + f"richieste/{richiesta.pk}").status_code == 404
