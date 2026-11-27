<p align="center"><img src="https://raw.githubusercontent.com/EduWISP/.github/main/branding/eduwisp-mark.svg" alt="EduWISP" height="72"></p>

# eduwisp-api

**API per le app mobili** · *Mobile app API*

API JSON (`/api/app/v1/`) per le app EduWISP del personale della scuola, delle famiglie e degli studenti ([ADR-0022](https://eduwisp.org/docs/decisioni/0022-app-mobili/)), con **gli stessi permessi del portale**: il docente vede solo le proprie classi, il dirigente l'istituto, la famiglia solo i propri figli.

> 🧪 **Stato: prototipo v0.** Prova sulla [demo](https://demo.eduwisp.org) con utente `demo` e password `demo` (sola lettura).

🇬🇧 *JSON API for the EduWISP staff, family and student apps (ADR-0022), with the same permissions as the web portal. **Status: prototype v0.***

## Chiamate / Endpoints

| Chiamata | A cosa serve |
|---|---|
| `POST accedi` | utente e password → token per questo telefono (30 giorni, revocabile) |
| `POST esci` | revoca il token |
| `GET io` | persona, ruoli, ruolo attuale e **menu** dell'app (docente, coordinatore, dirigente, famiglia) |
| `GET classi`, `GET classi/<id>` | classi visibili (`?solo=coordinate` per il coordinatore) e dettaglio con studenti, tablet, app |
| `POST classi/<id>/sblocchi`, `POST sblocchi/<id>/termina` | sblocco di un'app per la lezione e richiusura (solo docenti della classe) |
| `GET richieste`, `GET richieste/<id>` | richieste di app visibili (ADR-0021) |
| `POST richieste/<id>/decisione`, `POST richieste/<id>/parere` | decisione motivata del docente, parere motivato della famiglia |
| `GET riepilogo` | richieste in attesa, per il controllo periodico dell'app |
| `GET figli` | figli della famiglia |
| `GET/POST/DELETE vedi-come` | «vedi come» dell'amministratore, in sola lettura e registrato |

Tutte le chiamate tranne `accedi` vogliono `Authorization: Bearer <token>`; `?membership=<id>` sceglie il ruolo per chi ne ha più di uno. Le risposte hanno `Cache-Control: no-store`. Gli account in sola lettura (gruppo `sola-lettura`) e il «vedi come» non possono modificare nulla; gli accessi fuori ambito rispondono 404 e sono registrati.

## Installazione / Setup

```python
INSTALLED_APPS += ["eduwisp_api"]
```

```python
# urls.py
urlpatterns += [path("", include("eduwisp_api.urls"))]
```

Il ruolo [`ansible-eduwisp`](https://github.com/EduWISP/ansible-eduwisp) lo configura da solo e limita i tentativi di accesso.

## Dipendenze / Dependencies

[`eduwisp-users`](https://github.com/EduWISP/eduwisp-users), [`eduwisp-school`](https://github.com/EduWISP/eduwisp-school), [`eduwisp-devices`](https://github.com/EduWISP/eduwisp-devices), [`eduwisp-apps`](https://github.com/EduWISP/eduwisp-apps), [`eduwisp-audit`](https://github.com/EduWISP/eduwisp-audit)

## Privacy

Dati personali previsti e regole: [PRIVACY.md](PRIVACY.md). Il rispetto della normativa su privacy e minori è un vincolo bloccante ([ADR-0008](https://eduwisp.org/docs/decisioni/0008-conformita-normativa/)).

## Responsabile del modulo / Module owner

Cerchiamo persone che vogliano prendere in carico questo modulo! Proponiti in [Discussions](https://github.com/EduWISP/docs/discussions). / *Want to own this module? Say hi in Discussions.*

## Contribuire / Contributing

Vedi [CONTRIBUTING](https://github.com/EduWISP/.github/blob/main/CONTRIBUTING.md) e il [Codice di condotta](https://github.com/EduWISP/.github/blob/main/CODE_OF_CONDUCT.md). **Mai dati personali reali** di studenti, famiglie o personale.

## Licenza / License

**AGPL-3.0-or-later**, con termini aggiuntivi di attribuzione e tutela del nome (sezione 7): vedi [LICENSE](LICENSE) e [NOTICE.md](NOTICE.md). Chi usa o modifica EduWISP deve sempre indicare «Basato su EduWISP» e non può usare il nome e il logo per versioni modificate. Licenza scelta secondo le [linee guida AgID](https://eduwisp.org/docs/decisioni/0006-licenza/) per il software usato via rete.

*AGPL-3.0-or-later with additional attribution and trademark terms (section 7): see LICENSE and NOTICE.md.*

I contributi richiedono il [DCO](https://github.com/EduWISP/.github/blob/main/CONTRIBUTING.md#dco) (`git commit -s`).
