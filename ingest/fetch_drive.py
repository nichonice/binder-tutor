"""Henter nyeste ManaBox-backup/CSV fra hver vens delte Drive-mappe.
Vennerne deler deres backup-mappe med service-kontoens e-mail (Viewer)."""
import io

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload


def newest_file(creds, folder_id: str) -> tuple[str, bytes] | None:
    """Returnér (filnavn, indhold) for nyeste fil i mappen, ellers None."""
    svc = build("drive", "v3", credentials=creds, cache_discovery=False)
    res = svc.files().list(
        q=f"'{folder_id}' in parents and trashed = false",
        orderBy="modifiedTime desc",
        pageSize=1,
        fields="files(id, name, modifiedTime, size)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    files = res.get("files", [])
    if not files:
        return None
    f = files[0]
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, svc.files().get_media(
        fileId=f["id"], supportsAllDrives=True))
    done = False
    while not done:
        _, done = dl.next_chunk()
    return f["name"], buf.getvalue()
