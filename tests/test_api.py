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
