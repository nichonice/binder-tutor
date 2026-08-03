# Binder Tutor 🃏

Fælles overblik over vennegruppens Magic-samlinger. Brugerne logger ind med Google,
sætter hjerte på de kort de mangler, og ser hvem der har dem. Samlinger synkes fra
ManaBox (CSV-eksport i Google Drive) via et nightly job. Alt lever i Firestore.

## Arkitektur

```
Brugeren (web-app, Google-login)
  ├─ Venner:       se samlinger, filtrér, sæt hjerte direkte på kortene
  ├─ Mine Wants:   Scryfall-søgning + hjerte / import fra Archidekt·Moxfield → wants/{uid}
  ├─ Trading Hub:  tovejs-match + handelsbygger (regnes i browseren)
  ├─ Patch notes:  udmeldinger til gruppen, bor i PATCH_NOTES i index.html
  └─ Min profil:   driveFolderId + binder-status → users/{uid}

ManaBox (hver bruger)
  └─ CSV-eksport → egen Google Drive-mappe (delt med service-kontoen)
        └─ GitHub Action (nightly 02:00 UTC)
             ├─ main.py          læser users + wants FRA Firestore
             ├─ fetch_drive.py   henter nyeste .csv pr. bruger
             ├─ parse_manabox.py CSV-parser (.backup er krypteret, kan ikke bruges)
             ├─ import_lists.py  Archidekt/Moxfield serverside (CORS)
             ├─ prices.py        Scryfall bulk → pris + gameplay-felter pr. kort
             └─ skriver collections/{uid} + navneindeks tilbage
                  └─ web-appen læser live
```

Eksterne data hentes fra autoritative kilder frem for at vedligeholdes lokalt:
**Scryfall** til kortdata og priser, **ECB** (via frankfurter.dev) til valutakurs.

## Ved ændringer — læs dette først

**1. Enhver ændring brugerne kan mærke, skal have en ny post i `PATCH_NOTES`
øverst i `web/index.html` — i samme commit som ændringen.**

Vennegruppen er spredt over Teams og Snapchat, så appen er eneste sted alle får
beskeden. Bump `v`, skriv i almindeligt sprog hvad de får ud af det (ikke hvad koden
gør), og brug `todo`-feltet hvis de selv skal foretage sig noget:

```js
{
  v: "1.4", date: "12. august 2026",
  title: "Kort overskrift folk kan forstå",
  items: ["**Fed indledning.** Så forklaringen.", "`Kode` virker også."],
  todo: "Kun hvis brugerne selv skal gøre noget.",
},
```

Nyeste post øverst; `APP_VERSION` udledes af `PATCH_NOTES[0].v`. Alle får en grøn prik
på fanen og en banner indtil de har læst den. Rene refaktoreringer og usynlige
fejlrettelser kræver ingen note.

**2. Commit uden line-ending-støj.** Brug `git add ingest web` frem for `git add -A`
— nogle filer i repoet ligger med CRLF i working tree og LF i indekset, og fremstår
derfor som fuldt ændrede. En `.gitattributes` med `* text=auto` rydder det op
permanent, hvis du gider.

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
--only firestore:rules`). De giver: login kræves for at læse, du kan kun skrive dine
egne `users/{uid}` og `wants/{uid}`, og `collections` skrives kun af nat-jobbet.
Undercollections (`chunks`, `index`) har egne regler — rules cascader ikke.

### 4. Frontend
1. Indsæt Firebase web-config i `web/index.html`
2. Deploy til Firebase Hosting eller GitHub Pages
3. Log ind med Google → gå til **Min profil** → indsæt dit Drive mappe-ID

### 5. Hver bruger (selv-onboarding — ingen filer at redigere)
1. Log ind med Google (opretter automatisk `users/{uid}`)
2. **Min profil** → indsæt Drive mappe-ID (og del mappen med service-kontoen)
3. **Min profil → Mine bindere** → marker hvad der er til handel, låst til deck,
   eller ikke fysisk (lister)
4. **Mine Wants** → søg kort og sæt hjerte, eller importér fra Archidekt/Moxfield

## Datamodel (Firestore)

| Path | Skrives af | Indhold |
|---|---|---|
| `users/{uid}` | klient | `{name, email, photoURL, driveFolderId, pendingImports[], binderMode{}, notForTrade[]}` |
| `wants/{uid}` | klient + nat-job | `{cards: [{name, scryfallId, set, cn}], updated}` |
| `collections/{uid}` | nat-job | `{name, cardCount, uniqueCount, listCount, chunks, binders[], updated}` |
| `collections/{uid}/chunks/{n}` | nat-job | kortliste, opdelt efter byte-størrelse (≤ 1 MB/doc) |
| `collections/{uid}/index/names` | nat-job | `{cards: [[navn, mode, eur, antal], ...]}` — kompakt indeks til matching i browseren |

Kort i chunks bærer ManaBox-felterne (`name, set, cn, foil, qty, condition, rarity,
scryfallId, binder, binderType`) plus Scryfall-berigelse (`eur, cmc, ci, colors, type,
text, mana`).

**Binder-status** (`binderMode`) styrer alt: `trade` = til handel, `deck` = fysisk men
bundet i et deck, `list` = ikke fysisk (ManaBox-liste). Lister tælles hverken i
samlingen eller som match — ManaBox eksporterer dem i samme CSV som samlingen, så uden
det tælles kort dobbelt.

## TODO

- [x] Wants + venner i Firestore med Google-login (ingen friends.json/txt)
- [x] Priser på matches (`ingest/prices.py`, EUR fra Scryfall/Cardmarket)
- [x] Filtre, EUR/DKK-skift, hjerter direkte i samlinger, binder-styring
- [x] Lister tæller ikke som fysiske kort
- [x] Trading Hub med tovejs-match og handelsbygger
- [x] Stramme rules: login kræves for at læse
- [x] Keep-alive i `nightly.yml` — GitHub deaktiverer ellers schedulen efter
      60 dages inaktivitet i repoet
- [x] Advarsel i appen når en samling er over 30 dage gammel (`STALE_DAYS`)
- [x] Mobiloptimering + oprydning i dødt kode
- [x] Al matching flyttet til klienten via kompakt navneindeks — nye wants slår
      igennem med det samme
- [x] Kom i gang-tjekliste for nye brugere + eksport/import af wants
- [ ] Notifikationer ved nye matches (Teams-webhook i Action'en)
- [ ] App Store: share-sheet-upload i stedet for Drive-service-konto
