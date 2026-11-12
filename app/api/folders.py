"""Folders: groups of feeds the reader makes by hand.

Listing is open to any reader (the sidebar needs it); every change is
admin-only, like every other change to the shared feed list.
"""

from flask import jsonify, request

from app.api import api_admin, api_auth, bp, error
from app.db import get_db
from app.repo import folders as folders_repo


def _row(r) -> dict:
    return {"id": r["id"], "name": r["name"], "feeds": r["feeds"]}


def _name():
    """The submitted name, trimmed, or None when there is nothing left."""
    name = str((request.get_json(silent=True) or {}).get("name") or "").strip()
    return name or None


@bp.get("/folders")
@api_auth
def list_folders():
    return jsonify({"folders": [_row(r) for r in folders_repo.all_(get_db())]})


@bp.post("/folders")
@api_admin
def create_folder():
    name = _name()
    if name is None:
        return error("A folder needs a name.", 400)
    db = get_db()
    try:
        fid = folders_repo.create(db, name)
    except folders_repo.DuplicateName:
        return error(f"There is already a folder called {name}.", 409)
    db.commit()
    return jsonify(_row(folders_repo.get(db, fid)))


@bp.post("/folders/<int:folder_id>/rename")
@api_admin
def rename_folder(folder_id: int):
    db = get_db()
    if folders_repo.get(db, folder_id) is None:
        return error("No such folder.", 404)
    name = _name()
    if name is None:
        return error("A folder needs a name.", 400)
    try:
        folders_repo.rename(db, folder_id, name)
    except folders_repo.DuplicateName:
        return error(f"There is already a folder called {name}.", 409)
    db.commit()
    return jsonify(_row(folders_repo.get(db, folder_id)))


@bp.delete("/folders/<int:folder_id>")
@api_admin
def delete_folder(folder_id: int):
    """The folder goes; its feeds stay, unfiled."""
    db = get_db()
    if folders_repo.get(db, folder_id) is None:
        return error("No such folder.", 404)
    folders_repo.delete(db, folder_id)
    db.commit()
    return jsonify({"deleted": folder_id})
