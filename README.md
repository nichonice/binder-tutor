# Binder Tutor 🃏

Fælles overblik over vennegruppens Magic-samlinger. Brugerne logger ind med Google,
sætter hjerte på de kort de mangler, og ser hvem der har dem. Samlinger synkes fra
ManaBox (Google Drive-backup) via et nightly job. Alt lever i Firestore — ingen
`friends.json` eller wants-txt mere.

## Arkitektur

```
Brugeren (web-app, Google-login)
  ├─ Mine Wants: Scryfall-søgning + hjerte / import fra Archidekt·Moxfield → wants/{uid}
  └─ Min profil: driveFolderId → users/{uid}

ManaBox (hver bruger)
  └─ auto-backup → egen Google Drive-mappe (delt med service-kontoen)
        └─ GitHub Action (nightly 02:00 UTC)
             ├─ main.py          læser users + wants FRA Firestore
             ├─ fetch_drive.py   henter nyeste backup pr. bruger
             ├─ parse_manabox.py CSV nu / .backup-format når prøvefil haves
             ├─ match_wants.py   cross-matcher alles wants mod alles samlinger
             ├─ prices.py        beriger matches med EUR (Scryfall/Cardmarket)
             └─ skriver collections/{uid} + matches/{uid} tilbage
                  └─ web-appen læser live
```

## Setup

Se den udførlige `binder-tutor-SETUP.md`. Kort fortalt:

### 1. Firebase/GCP
1. Firebase-projekt med **Firestore** aktiveret
2. **Authentication → Sign-in method → Google → Enable**
3. Aktivér **Google Drive API** i GCP-konsollen
4. Opret **service-konto** med rollen `Cloud Datastore User`, download JSON-nøglen,
   notér dens e-mail

### 2. GitHub
1. Push repoet
2. Secret **`GCP_SA_KEY`** = hele service-konto-JSON'en
3. Kør "Nightly sync" manuelt for at teste

### 3. Firestore rules
Deploy `firestore.rules` (Console → Firestore → Rules, eller `firebase deploy
--only firestore:rules`). De giver: alle kan læse, du kan kun skrive dine egne
`users/{uid}` og `wants/{uid}`, og `collections`/`matches` skrives kun af nat-jobbet.

### 4. Frontend
1. Indsæt Firebase web-config i `web/index.html`
2. Deploy til Firebase Hosting eller GitHub Pages
3. Log ind med Google → gå til **Min profil** → indsæt dit Drive mappe-ID

### 5. Hver bruger (selv-onboarding — ingen filer at redigere)
1. Log ind med Google (opretter automatisk `users/{uid}`)
2. **Min profil** → indsæt Drive mappe-ID (og del mappen med service-kontoen)
3. **Mine Wants** → søg kort og sæt hjerte, eller importér fra Archidekt/Moxfield

## Datamodel (Firestore)

| Path | Skrives af | Indhold |
|---|---|---|
| `users/{uid}` | klient | `{name, email, photoURL, driveFolderId}` |
| `wants/{uid}` | klient | `{cards: [{name, scryfallId, set, cn}]}` |
| `collections/{uid}` | nat-job | navn, kortantal, antal chunks, updated |
| `collections/{uid}/chunks/{n}` | nat-job | kortliste i bidder a 800 (≤ 1 MB/doc) |
| `matches/{uid}` | nat-job | `{ownerUid: {cards:[...], totalEur}}` |

## TODO

- [ ] **Drive-backup-parser**: `parse_backup()` venter på en `.backup`-prøvefil
      (format bekræftet: `manabox-YYYY-MM-DD (enhed).backup`)
- [x] Wants + venner i Firestore med Google-login (ingen friends.json/txt)
- [x] Priser på matches (`ingest/prices.py`, EUR fra Scryfall/Cardmarket)
- [ ] Notifikationer ved nye matches (Discord-webhook i Action'en)
- [ ] App Store: share-sheet-upload i stedet for Drive-service-konto (se chat)
