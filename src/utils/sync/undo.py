def undo_sync_run(db, user_id: str, sync_run_id: str) -> dict:
    run = db.get_sync_run(sync_run_id)
    if not run or run["user_id"] != user_id:
        raise PermissionError("Sync run not found for user")
    as_of = run["as_of_date"]
    if hasattr(as_of, "isoformat"):
        as_of_str = as_of.isoformat()
    else:
        as_of_str = str(as_of)

    restored = deleted = skipped = 0
    for item in db.list_sync_run_items(sync_run_id):
        if item["outcome"] != "written" or not item.get("account_id"):
            continue
        current = db.get_account_value(item["account_id"], as_of_str)
        new_val = float(item["new_value_gbp"]) if item["new_value_gbp"] is not None else None
        if current is None or new_val is None or abs(current - new_val) > 0.001:
            skipped += 1
            continue
        if item.get("had_previous"):
            db.save_account_value(item["account_id"], as_of_str, float(item["previous_value_gbp"]))
            restored += 1
        else:
            db.delete_account_value(item["account_id"], as_of_str)
            deleted += 1

    notes = f"Undo: restored={restored}, deleted={deleted}, skipped={skipped}"
    run = db.mark_sync_run_undone(sync_run_id, notes=notes)
    return {"restored": restored, "deleted": deleted, "skipped": skipped, "run": run}
