"""Henter nyeste ManaBox-backup/CSV fra hver vens delte Drive-mappe.
Vennerne deler deres backup-mappe med service-kontoens e-mail (Viewer)."""
import io

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload


def newest_file(creds, folder_id: str) -> tuple[str, bytes] | None:
    """Returnér (filnavn, indhold) for nyeste brugbare fil i mappen, ellers None.

    Vi foretrækker nyeste .csv. ManaBox' auto-backup lægger krypterede
    .backup-filer i samme mappe, og de kan ikke læses serverside — uden dette
    filter ville en nyere .backup skygge for en fuldt brugbar CSV.
    Findes der ingen CSV, falder vi tilbage til nyeste fil, så parse_manabox
    kan give en sigende fejl i stedet for tavshed."""
    svc = build("drive", "v3", credentials=creds, cache_discovery=False)
    res = svc.files().list(
        q=f"'{folder_id}' in parents and trashed = false",
        orderBy="modifiedTime desc",
        pageSize=50,
        fields="files(id, name, modifiedTime, size)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    files = res.get("files", [])
    if not files:
        return None
    # Drive's 'contains'-operator laver kun prefix-match på ordniveau, så
    # endelsen filtreres her i stedet for i query'en.
    csvs = [f for f in files if f["name"].lower().endswith(".csv")]
    f = csvs[0] if csvs else files[0]
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, svc.files().get_media(
        fileId=f["id"], supportsAllDrives=True))
    done = False
    while not done:
        _, done = dl.next_chunk()
    return f["name"], buf.getvalue()
