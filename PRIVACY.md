# Privacy — eduwisp-api

Documento vivo. Riferimenti: [ADR-0022](https://eduwisp.org/docs/decisioni/0022-app-mobili/), [quadro normativo](https://eduwisp.org/docs/sicurezza-privacy/quadro-normativo/).

- **Dati propri**: solo i token delle app (utente, nome del telefono indicato dall'app, date di creazione, ultimo uso e scadenza). Il server conserva l'impronta del segreto, mai il segreto.
- **Dati mostrati**: gli stessi del portale, secondo il ruolo; nessun dato sanitario, nessuna posizione.
- Le risposte non vanno nelle cache (`Cache-Control: no-store`).
- Il «vedi come» dell'amministratore è in sola lettura e registrato nel registro delle operazioni, come nel portale.

---

🇬🇧 *Only app tokens are stored (hashed). Data shown follows the portal's role permissions; responses are not cached; admin "view as" is read-only and audited.*
