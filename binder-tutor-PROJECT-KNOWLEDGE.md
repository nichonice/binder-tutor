# Binder Tutor — projekt-viden (handoff til Claude Project)

Dette dokument samler alt relevant om Binder Tutor-projektet, så et Claude Project
kan arbejde videre uden at kende chathistorikken. Læg det ind som knowledge-fil i
projektet.

> **Sidst opdateret:** august 2026 (v1.5 — matching flyttet til klienten,
> onboarding, wants-backup). Erstatter den tidligere version af dette dokument.

---

## 1. Hvad er Binder Tutor?

En webapp der lader en vennegruppe se hinandens Magic: The Gathering-samlinger,
tagge ønskekort ("wants") og finde ud af hvem der ejer de kort man mangler.
Samlinger kommer fra ManaBox (CSV-eksport i Google Drive), synkes via et nightly
job til Firestore, og vises i en statisk webapp med Google-login.

**Ejer/udvikler:** Nicholas (IT-konsulent, ITAGIL ApS). Windows 11, PowerShell,
bruger allerede GitHub + Firebase/Firestore til andre projekter.

**Status:** v1.5 — kører i produktion for vennegruppen. Login, samlinger, wants,
matching, priser, filtrering, binder-styring og Trading Hub virker end-to-end.

**Designprincip:** eksterne data hentes fra autoritative tredjeparts-API'er frem
for at blive vedligeholdt lokalt. Scryfall er eneste kilde til kortdata og priser;
ECB (via frankfurter.dev) er eneste kilde til valutakurs.

---

## 2. Arkitektur

```
Brugeren (webapp, Google-login)
  ├─ Venner:     se samlinger, filtrér, sæt hjerte direkte på kortene
  ├─ Mine Wants: Scryfall-søgning + hjerte / import fra Archidekt·Moxfield → wants/{uid}
  └─ Min profil: driveFolderId + hvilke bindere der er til handel → users/{uid}

ManaBox (hver bruger)
  └─ CSV-eksport → egen Google Drive-mappe (delt med service-kontoen som Viewer)
        └─ GitHub Action (nightly 02:00 UTC / 04:00 dansk)
             ├─ main.py          læser users + wants FRA Firestore
             ├─ fetch_drive.py   henter nyeste .csv pr. bruger
             ├─ parse_manabox.py parser CSV (.backup er krypteret, kan ikke bruges)
             ├─ import_lists.py  henter Archidekt/Moxfield-lister + Scryfall-berigelse
             ├─ prices.py        Scryfall bulk → pris + gameplay-felter (gzippet JSONL)
             └─ skriver collections/{uid} + navneindeks tilbage
                  └─ webappen (GitHub Pages) læser live fra Firestore
```

**Stack:** Python 3.12 (ingest), vanilla HTML/JS + Firebase modular SDK (frontend),
Firestore (data), GitHub Actions (scheduler), GitHub Pages (hosting).

---

## 3. Firestore-datamodel

| Path | Skrives af | Indhold |
|---|---|---|
| `users/{uid}` | klient | `{name, email, photoURL, driveFolderId, pendingImports[], binderMode{}, notForTrade[]}` |
| `wants/{uid}` | klient + nat-job | `{cards: [{name, scryfallId, set, cn}], updated}` |
| `collections/{uid}` | nat-job | `{name, cardCount, uniqueCount, listCount, chunks, binders[], updated}` |
| `collections/{uid}/chunks/{n}` | nat-job | `{cards: [...]}` — se kortformat nedenfor |
| `collections/{uid}/index/names` | nat-job | `{rows: ["navn\tmode\teur\tantal\n...", ...], count}` — kompakt indeks til matching i browseren |

`uid` = Google-uid fra Firebase Auth.

### Kortformat i `chunks`

Felter fra **ManaBox-CSV'en**:
`name, set, setName, cn, foil, qty, condition, lang, rarity, scryfallId, binder, binderType`

Felter påført af **nat-jobbet fra Scryfall** (kun hvis `scryfallId` kan slås op):
`eur` (foil-bevidst pris), `cmc`, `ci` (color_identity), `colors`, `type` (type_line),
`text` (oracle_text), `mana` (mana_cost)

Bemærk: felterne udelades hvis Scryfall-værdien er tom. Farveløse kort har derfor
**ingen** `ci`-nøgle — frontenden skal behandle manglende/tom `ci` som farveløs.

### Navneindekset

`collections/{uid}/index/names` er `{rows: [...], count}`, hvor `rows` er tekstblokke
med én tab-separeret linje pr. kort: `navn \t mode \t pris \t antal`. `mode` er
`t`/`d`/`l` og navnet er lowercased. Ét entry pr. unikt kortnavn, med den
mest handelsvenlige tilstand og højeste pris blandt eksemplarerne. Ejerens
`binderMode` er allerede anvendt af nat-jobbet.

Det er nøglen til at matche i browseren: en fuld samling fylder ~4,6 MB i chunks
(regeltekst m.m.), indekset ~170 kB. Ti venners indeks er under 2 MB — acceptabelt
på mobil, hvilket alles fulde samlinger ikke ville være.

### `binderMode` — handel vs. deck vs. liste

`collections/{uid}.binders` er en liste af objekter `{name, type, mode, unique, qty}`,
hvor `type` er ManaBox' rå `Binder Type` og `mode` er den udledte status.

`users/{uid}.binderMode` er et map `{"<bindernavn>": "trade"|"deck"|"list"}` med
ejerens eventuelle overstyring:

| mode | Betyder | Tæller i samlingen | Kan matches |
|---|---|---|---|
| `trade` | fysisk, til handel | ja | ja |
| `deck` | fysisk, bundet i et deck | ja | kun hvis man slår "vis låste" til |
| `list` | ikke fysisk (ManaBox-liste/wishlist) | **nej** | **nej** |

Udledes af `Binder Type` når brugeren ikke har valgt: `list`/`wish` → `list`,
`deck` → `deck`, ellers `trade`. Ejerens valg vinder altid.

Håndhæves **både** i nat-jobbet (tællere) og i frontenden (visning og matches).
Det er bevidst dobbelt: tællerne skal være rigtige i meta-dokumentet, men ejeren
skal kunne ændre status uden at vente på et sync.

Feltet hed `lockedBinders[]` i v1.1. Frontenden læser stadig det gamle felt som
fallback (alle navne i listen tolkes som `deck`), så ingen skal sætte op igen.

### Security rules

Login kræves for at læse noget som helst (`request.auth != null`). Du kan kun skrive
dine egne `users`/`wants`; `collections` og undercollections skrives kun af nat-jobbet
(Admin SDK går udenom rules).

> Husk at `index`-undercollection skal have sin egen `match`-blok — Firestore-rules
> cascader ikke ned i undercollections.

---

## 4. Kodebase (filer i repoet)

```
binder-tutor/
├─ .github/workflows/nightly.yml   cron 02:00 UTC + workflow_dispatch (manuel)
├─ firestore.rules                 pr-bruger skrive-adgang
├─ README.md
├─ ingest/
│  ├─ main.py            orkestrering + enrich_card() + chunk_cards()
│  ├─ fetch_drive.py     nyeste .csv fra Drive (filtrerer i Python, ikke i query)
│  ├─ parse_manabox.py   CSV-parser (+ .backup sniffer der giver klar fejl)
│  ├─ import_lists.py    Archidekt/Moxfield-fetch + Scryfall enrich() (batch 75)
│  ├─ prices.py          Scryfall bulk → load_card_map(ids) (pris + gameplay)
│  └─ requirements.txt   google-cloud-firestore, google-api-python-client, google-auth
└─ web/
   └─ index.html         hele frontenden (login, Venner+filtre, Wants, matches, profil)
```

Firebase web-config er bagt ind i `web/index.html` (projekt: `binder-tutor`).

**Centrale funktioner:**

- `prices.load_card_map(ids)` — streamer Scryfalls gzippede JSONL linje for linje og
  beholder kun de ID'er der er brug for. `load_price_map()` findes som alias.
- `main.enrich_card(card, cmap)` — påfører pris + gameplay-felter. Foil-kort får
  `eur_foil` hvis den findes, ellers almindelig `eur`.
- `main.chunk_cards(cards)` — byte-baseret opdeling (700 kB / max 800 kort pr. chunk).
- Frontend `F`-objektet i `renderFriends()` holder al filterstate på modulniveau, så
  filtre overlever et valutaskift (som gentegner hele viewet).

### Trading Hub

`renderTrade()` + `buildTrade()` i `web/index.html`. Regner **udelukkende i browseren**
ud fra data der allerede er læsbare — ingen nye Firestore-felter ud over
`users/{uid}.notForTrade[]`:

- *hvad de har som jeg vil have* ← deres navneindeks ∩ mine `wants`
- *hvad jeg har som de vil have* ← min egen `collections`-chunks ∩ deres `wants`

Begge retninger er live — et nyt hjerte slår igennem med det samme. Oversigten koster
ca. 30 doc-reads (~2 MB for ti venner); først når man åbner en konkret handel hentes
den persons fulde chunks, så sæt, stand og binder kan vises.

Kun kort i `trade`-tilstand indgår — `deck` og `list` filtreres fra i begge retninger,
og begge parters `notForTrade` respekteres. Rækkerne sorteres efter *gensidigt* fit
(`min(iGet, theyGet)`), så tovejs-handler ligger øverst.

**Designvalg — eksklusion, ikke inklusion:** man markerer kun de få kort man alligevel
ikke vil af med (`notForTrade`), i stedet for at tagge hvad man vil handle. En
inklusionsliste over 5.000 kort bliver aldrig vedligeholdt; en eksklusionsliste
forbliver kort. Binder-tilstanden gør grovarbejdet.

Handler afsluttes med **kopiér-som-tekst** til Snapchat/Teams — bevidst ingen
forslags-collection med accepteret/afvist-status i Firestore. Teksten (og en boks i
UI'et) slutter altid med `REMINDER`-konstanten: scan nye kort ind i ManaBox og slet
dem I gav væk. Uden det matcher appen videre på kort folk ikke ejer, og datakvaliteten
falder fra hinanden for hele gruppen.

### Patch notes — hvordan man udgiver en ændring

Vennegruppen er spredt over Teams og Snapchat, så udmeldinger sker **i appen**, ikke
i chats. Patch notes bor i `PATCH_NOTES`-arrayet øverst i `web/index.html`:

```js
{ v:"1.3", date:"...", title:"...", items:["**Fed** tekst og `kode` virker"], todo:"..." }
```

Nyeste post øverst; `APP_VERSION` udledes automatisk af `PATCH_NOTES[0].v`. Bump
versionen i samme commit som ændringen — så får alle en grøn prik på fanen og en
banner, indtil de har åbnet fanen (`localStorage["bt.seen"]`). `todo`-feltet er til
ting brugerne selv skal gøre, og vises fremhævet.

Al tekst escapes før `**fed**` og `` `kode` `` oversættes, så notes kan ikke
injicere HTML. Delebeskeden på Teams/Snapchat er derefter bare tre linjer + link.

---

## 5. Beslutninger & hårdt lærte lektier (VIGTIGT)

Disse er fundet gennem fejlfinding — respektér dem, så de ikke genopstår:

1. **ManaBox `.backup` er AES-krypteret** (Hive-box, nøgle i telefonens secure
   storage). Kan IKKE dekrypteres serverside. Datakilden er ManaBox **CSV-eksport**
   lagt i Drive-mappen.

2. **Drives `contains`-operator laver kun prefix-match på ordniveau.**
   `name contains '.csv'` virker derfor ikke som filendelse-filter. `fetch_drive.py`
   henter de 50 nyeste filer og filtrerer på `.endswith('.csv')` i Python, med
   fallback til nyeste fil så `parse_backup()` stadig kan give en sigende fejl.
   *Uden dette skygger en nyere `.backup` for en fuldt brugbar CSV, og synket
   fejler tavst.*

3. **Scryfall kræver headers** (`User-Agent` + `Accept`), ellers HTTP 400.

4. **Scryfall bulk-format:** feltet hedder `jsonl_download_uri` (ikke `download_uri`),
   og filen er gzippet **JSONL** (ét kort pr. linje), ikke en JSON-array.
   `prices.py` håndterer begge for en sikkerheds skyld. Filen er ~500 MB udpakket —
   stream den, og filtrér til de ID'er du faktisk bruger.

5. **`oracle_text`, `type_line`, `mana_cost` og `colors` mangler på top-niveau for
   DFC'er og split-kort** — de ligger på `card_faces[]`. `color_identity` og `cmc`
   ligger derimod altid på top-niveau. `prices._face_text()` samler faces med `//`.

6. **Firestore tillader IKKE arrays inde i arrays.** `{"cards": [[navn, mode], ...]}`
   fejler med `400 Nested arrays are not allowed` — og først når man skriver, ikke
   når man bygger dokumentet. Navneindekset gemmes derfor som en liste af
   *tekstblokke* med tab-separerede linjer, hvilket samtidig er mere kompakt end
   objekter (feltnavne gentages ikke pr. kort). Lokale tests der kun serialiserer
   til JSON fanger det ikke — valider mod Firestores typeregler i stedet.

7. **Firestore-dokumenter må max fylde 1 MB.** Med regeltekst på kortene kan et fast
   antal kort pr. chunk sprænge grænsen (planeswalkere/sagaer er lange). Derfor
   pakker `chunk_cards()` efter faktisk byte-størrelse. Testet: 5.000 kort med
   ~1,2 kB regeltekst hver → 12 chunks, største 0,67 MB.

8. **Archidekt & Moxfield blokerer browser-fetch (CORS).** Import kan derfor ikke
   ske client-side. Løsning: klienten gemmer URL'en i `users/{uid}.pendingImports`,
   og nat-jobbet henter den serverside og fletter ind i wants.

9. **Importerede wants mangler billeder**, fordi de kun har navn. `enrich_wants()`
   i nat-jobbet slår manglende kort op via Scryfalls `/cards/collection` (batch 75)
   og tilføjer `scryfallId`. Kører hver nat, så det er selvhelbredende.

10. **ManaBox eksporterer lister og wishlists i SAMME CSV som samlingen.** Eneste
   forskel er kolonnen `Binder Type`. Behandler man hver række som et fysisk kort,
   tælles kort dobbelt: har man ét eksemplar og også har kortet på en liste, står
   der to. Lister må aldrig tælle med i `cardCount`/`uniqueCount` eller optræde
   som match. Se `auto_mode()` i `main.py` og `binderMode` i afsnit 3.

11. **Farveløse kort har tom `color_identity`.** I filterlogikken betyder det to ting:
   de matcher chippen "C", *og* de er "indeholdt i" enhver farveidentitet (et
   farveløst kort passer i alle decks). Behandl dem ikke som en femte farve.

12. **Firebase web-apiKey er IKKE en hemmelighed** — den skal ligge i klartekst i
    frontenden. GitHub secret-scanning flager den fejlagtigt; luk alarmen som
    "won't fix". Beskyttelsen er Firestore-rules, ikke nøglen. Læg dog API-key-
    restriktioner på i Google Cloud (HTTP referrers + API-restriktion) — og HUSK at
    inkludere `binder-tutor.firebaseapp.com/*` og `.web.app/*`, ellers brækker
    Google-login-handleren.

13. **GitHub Pages cacher aggressivt.** Efter deploy: hard-refresh + cache-bust med
    `?v=N` i URL'en. Bekræft ny version via Ctrl+U (søg efter et kendt nyt string).

14. **Config forsvinder ved fil-overskrivning.** Firebase-config er nu bagt ind i
    `index.html`, så den ikke tabes når frontenden opdateres.

15. **`README.md`, `firestore.rules` og `.gitignore` ligger med CRLF i working tree
    men LF i git-indekset**, så de fremstår som fuldt ændrede i `git diff`. Brug
    `git add ingest web` frem for `git add -A` for at undgå støj i commits — eller
    ryd op én gang for alle med en `.gitattributes` (`* text=auto`).

---

## 6. Åbne punkter / næste skridt

- [x] **Keep-alive** i `nightly.yml` — GitHub deaktiverer ellers schedulen efter
      60 dages inaktivitet i repoet.
- [x] **Snappy matches** — løst i v1.5 via navneindekset. `match_wants.py` og
      `matches/`-collection er fjernet.
- [ ] **Teams-webhook** ved nye matches — gruppen bruger Teams og Snapchat, ikke
      Discord. Nicholas er Power Platform-konsulent, så en indgående webhook er
      hurtigt sat op.
- [ ] **App Store (fremtid):** brug native share-sheet-upload i stedet for Drive +
      service-konto. UNDGÅ `drive.readonly` OAuth-scope — det udløser årlig CASA-
      audit ($500-4500). `drive.file` + Google Picker er non-restricted alternativ.
      (Gælder kun brugervendt OAuth; en service-konto med delte mapper er upåvirket.)

---

## 7. Eksterne services & quirks (opslagsværk)

- **Scryfall API:** kræver UA+Accept.
  - Bulk: `/bulk-data/default_cards` → `jsonl_download_uri` (gzip JSONL, ~500 MB udpakket)
  - Batch-opslag: `POST /cards/collection` (max 75 identifiers)
  - Autocomplete: `/cards/autocomplete?q=`
  - Søgning: `/cards/search?q=...&unique=cards` — fuld Scryfall-syntaks, 175 kort
    pr. side, `has_more` + `next_page` til paginering. Frontenden bruger den til
    avanceret søgning og stopper ved 5 sider (875 kort).
  - CORS er tilladt fra browser. Priser: `prices.eur` / `prices.eur_foil`.
- **frankfurter.dev** (ECB-kurser): `https://api.frankfurter.dev/v1/latest?from=EUR&to=DKK`.
  Gratis, ingen nøgle, CORS-venlig. `api.frankfurter.app` redirecter hertil — brug
  `.dev` direkte for at undgå redirect. Frontenden cacher kursen pr. dag i
  localStorage med 7,46 som fallback. DKK er fastkursbundet til EUR (~7,46-7,47).
- **ManaBox:** ingen offentlig API. CSV-eksport = ukrypteret kilde. `.backup` =
  krypteret, ubrugelig serverside. Cloud Sync (Pro) synker kun mellem egne enheder.
  CSV-kolonner der bruges: `Name, Set code, Set name, Collector number, Foil,
  Rarity, Quantity, Condition, Language, Scryfall ID, Binder Name, Binder Type`.
  Kolonnenavne har ændret sig før — `parse_manabox._first()` accepterer varianter.
- **Archidekt:** `GET https://archidekt.com/api/decks/{id}/` → `cards[].card.oracleCard.name`.
- **Moxfield:** collection `GET /v1/collections/{id}`; deck `GET /v3/decks/all/{id}`.
  Client-side blokeret af CORS — kun serverside.
- **Cardmarket/CardTrader (til handel):** DKK-pris = EUR trend × multiplier. "Trend 7"
  = EUR × 7 (≈ reel kurs 7,46, altså næsten fuld pris). Bulk-køb: sigt efter ×6-6,5.

---

## 8. Forslag til Claude Project-instruktioner

Indsæt i projektets "instructions"-felt:

> Dette projekt er Binder Tutor, en webapp der samler en Magic-vennegruppes ManaBox-
> samlinger i Firestore og matcher dem mod hver persons wants. Stack: Python-ingest
> (GitHub Actions nightly) + vanilla JS/Firebase-frontend + Firestore + GitHub Pages.
> Se knowledge-filen for arkitektur, datamodel, kodebase og hårdt lærte lektier —
> respektér især afsnit 5 (fx: ManaBox .backup er krypteret, brug CSV; Scryfall bulk
> er gzippet JSONL; DFC-felter ligger på card_faces; Firestore-chunks skal pakkes
> efter byte-størrelse; Archidekt/Moxfield-import skal ske serverside pga. CORS).
> Hent altid data fra autoritative tredjeparts-API'er (Scryfall til kortdata og
> priser, ECB til valuta) frem for at vedligeholde det lokalt.
> Brugeren er teknisk (IT-konsulent, PowerShell/Windows 11). Svar på dansk, vær
> konkret, udfordr gerne antagelser og foreslå bedre løsninger.
> **Ved kodeændringer: hold ændringer minimale, og afslut ALTID med en præcis,
> nummereret trin-for-trin-liste over hvad brugeren selv skal gøre — hvilke filer
> der er ændret, hvilke kommandoer der skal køres (PowerShell), og hvad der skal
> klikkes hvor i konsollerne. Ingen "husk at deploye" uden at skrive præcis hvordan.**
>
> **Enhver ændring brugerne kan mærke, SKAL følges af en ny post i `PATCH_NOTES`
> øverst i `web/index.html` — i samme commit som ændringen.** Bump `v`, skriv i
> almindeligt sprog hvad de får ud af det (ikke hvad koden gør), og brug `todo`-feltet
> hvis de selv skal foretage sig noget. Vennegruppen er spredt over Teams og Snapchat,
> så appen er eneste sted alle får beskeden. Spørg ikke om lov — gør det som en del af
> opgaven. Rene refaktoreringer og fejlrettelser ingen kan se, kræver ingen note.

---

## 9. Filer at uploade til projektet

Ud over dette dokument, læg disse i projektets knowledge:

- hele den aktuelle kodebase (kildefilerne fra repoet)
- `binder-tutor-SETUP.md` — komplet setup fra bunden
- `binder-tutor-MIGRATION-v2.md` — opgradering fra v1
- `binder-tutor-venne-guide-v2.docx` — onboarding-guide til venner
