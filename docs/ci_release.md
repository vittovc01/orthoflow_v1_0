# Verifiche automatiche e rilascio

Il workflow OrthoFlow CI parte sulle pull request verso main, sui push a main e manualmente. Non ha credenziali di produzione né permessi di scrittura. I test Python compilano tutti i sorgenti, eseguono il test esistente dello scarico, renderizzano login e pagine operative con un backend in memoria che rifiuta scritture, e provano apertura/navigazione/riapertura del menu con il frontend Streamlit reale su telefono e desktop.

Il secondo controllo crea un PostgreSQL 15 temporaneo con uno schema minimo di contratto, carica le cinque funzioni SQL operative dal repository, attiva il trigger di magazzino ed esegue tutti i test SQL transazionali esistenti. Non carica il ripristino una tantum delle giacenze e non si collega a Supabase. Il test non certifica l'intero schema, RLS, Storage, OCR esterno o i permessi di produzione.

## Blocco prima del deploy

Streamlit Community Cloud segue main: un controllo eseguito dopo un push diretto non impedisce quel deploy. Le modifiche devono passare da branch e pull request; attendere entrambi i controlli prima del merge.

Un amministratore GitHub deve attivare in Settings → Branches (o Rulesets) la protezione di main:
- Require a pull request before merging.
- Require status checks to pass before merging: Python e interfaccia e Magazzino e prezzi.
- Require branches to be up to date before merging.
- Bloccare i force push e applicare le regole anche agli amministratori, senza bypass per l'integrazione.

Il connettore attuale restituisce 403 sulle impostazioni di protezione: questa parte non è configurabile da questa sessione. La sola presenza del workflow non rende main protetto.

## Staging

La CI fornisce un ambiente temporaneo di test, non uno staging pubblico. Un'eventuale app di staging deve seguire un branch separato e usare un progetto/database e Storage separati con dati sintetici, mai le credenziali della produzione.

## Esecuzione locale

Usare Python 3.13, installare requirements-ci.txt e il browser con python -m playwright install chromium. Eseguire python -m compileall -q ., python tests/test_scarico_form.py e python -m pytest. Per i test SQL avviare un PostgreSQL 15 locale con database orthoflow_ci e password ci_only ed eseguire bash tests/run_database_tests.sh solo sul database di prova appena creato.

