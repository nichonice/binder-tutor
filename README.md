# Binder Tutor 🃏

Fælles overblik over vennegruppens Magic-samlinger. Nightly sync fra ManaBox
(Google Drive-backup) → Firestore → statisk web-app med "hvem har mine wants"-matching.

## Arkitektur

```
ManaBox (hver ven)
  └─ auto-backup → egen Google Drive-mappe (delt med service-kontoen)
        └─ GitHub Action (nightly 02:00 UTC)
             ├─ fetch_drive.py   henter nyeste fil pr. ven
             ├─ parse_manabox.py CSV nu / backup-format når prøvefil haves
             ├─ match_wants.py   cross-matcher wants (wants/*.txt) mod alle samlinger
             └─ main.py          skriver til Firestore
                  └─ web/index.html (Firebase Hosting / GitHub Pages) læser live
```

## Setup

### 1. Firebase/GCP
1. Brug dit eksisterende Firebase-projekt (eller opret et) med **Firestore** aktiveret
2. Aktivér **Google Drive API** i GCP-konsollen for projektet
3. Opret en **service-konto** (ingen roller nødvendige ud over `Cloud Datastore User`),
   download JSON-nøglen
4. Notér service-kontoens e-mail (`xxx@PROJEKT.iam.gserviceaccount.com`)

### 2. GitHub
1. Opret repo, push dette indhold
2. `Settings → Secrets and variables → Actions` → ny secret **`GCP_SA_KEY`**
   med hele indholdet af service-kontoens JSON-nøgle
3. Actions-fanen → kør "Nightly sync" manuelt for at teste

### 3. Hver ven
1. ManaBox → aktivér auto-backup til Google Drive (eller læg CSV-eksporter i en mappe)
2. Del backup-mappen med service-kontoens e-mail (**Viewer** er nok)
3. Send mappe-ID'et (fra Drive-URL'en) → indsæt i `friends.json`
4. Læg wants i `wants/<navn>.txt` (én kortlinje pr. linje, `#` = kommentar)

### 4. Frontend
1. Indsæt Firebase web-config i `web/index.html`
2. Deploy: `firebase deploy --only hosting` (eller GitHub Pages fra `web/`)
3. Firestore rules — read-only for alle, skrivning kun via service-kontoen (Admin SDK
   går udenom rules):

```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /{document=**} {
      allow read: if true;
      allow write: if false;
    }
  }
}
```

> Samlingerne bliver offentligt læsbare med de rules. Er det et problem, så slå
> anonym auth til og begræns `allow read` til kendte UIDs.

## Datamodel (Firestore)

| Path | Indhold |
|---|---|
| `friends/{id}` | navn, kortantal, antal chunks, sidst opdateret |
| `friends/{id}/chunks/{n}` | kortliste i bidder a 800 (≤ 1 MB pr. doc) |
| `wants/{id}` | `{cards: [navne]}` |
| `matches/{seekerId}` | `{ownerId: [kort ejeren har som seeker ønsker]}` |

## TODO

- [ ] **Drive-backup-parser**: `parse_backup()` i `ingest/parse_manabox.py` venter på
      en prøvefil fra en rigtig ManaBox-backup (sniffer allerede SQLite/zip-magic)
- [x] Priser på matches — `ingest/prices.py` henter Scryfall bulk data (EUR fra
      Cardmarket), beriger hvert match-kort og gemmer `totalEur` pr. ven
- [ ] Notifikationer ved nye matches (Discord-webhook i Action'en er den nemme løsning)
