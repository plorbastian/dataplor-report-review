"""Apply FP_UNCHAIN verdicts as ``/chain_id`` unchain observations.

For every verdict labelled `FP_UNCHAIN` in a review, emit an
observation that clears the POI's `/chain_id`. Uses the same
`ManualObservation` shape everything else in the pipeline emits, so
Kuebiko's PlaceUpdater picks it up.

The row shape matches what `brand_audit.core.observations._create_observations`
expects; we do NOT import it here to avoid a cross-repo hard dependency.
The caller passes an `observation_writer` callback with signature

    observation_writer(rows: list[dict], admin_id: int) -> ObservationResult

so this repo stays free of DB / api client wiring. The `apply` docstring
of that callback should confirm it stamps `type='ManualObservation'`.

After writing observations, the caller is responsible for triggering
Kuebiko PTU on the affected place_ids so the unchain propagates from
observations DB to `places`. Not doing that here avoids a hard
dependency on `bridge._trigger_place_updates_async_via_fargate`.

Signature of the writer:

    def write(rows, admin_id):
        # rows = [{"place_id": int, "path": "/chain_id",
        #          "value": "", "confidence": 1.0,
        #          "observation_type": "ManualObservation"}, ...]
        # value="" (empty string) clears the field. NEVER null:
        # PlaceUpdater silently drops jsonb-null patch values.
        ...
"""


def build_unchain_rows(verdicts):
    """Filter `verdicts` to the FP_UNCHAIN cohort and shape one
    observation row per POI. Empty list if no FPs.
    """
    rows = []
    for v in verdicts:
        if v.get("verdict") != "FP_UNCHAIN":
            continue
        rows.append({
            "place_id": int(v["id"]),
            "path": "/chain_id",
            "value": "",  # empty string, NOT null
            "confidence": 1.0,
            "observation_type": "ManualObservation",
        })
    return rows


def apply_unchains(verdicts, observation_writer, admin_id, *,
                   ptu_trigger=None):
    """Emit unchain observations for the FP_UNCHAIN verdicts.

    Args:
        verdicts: list returned by `review.review_pois`.
        observation_writer: callback(rows, admin_id) -> writer result.
            Must produce `type='ManualObservation'` rows.
        admin_id: operator's admins.id — never Ross's default.
        ptu_trigger: optional callable(place_ids). Called with the list
            of affected place_ids after the write succeeds. Typically
            wraps Kuebiko PTU via Fargate.

    Returns dict:
        {"fp_count": int, "written": int, "place_ids": list[int],
         "writer_result": <whatever writer returned>}

    A verdict list with zero FP_UNCHAIN entries returns fp_count=0 and
    does NOT call `observation_writer` or `ptu_trigger`.
    """
    rows = build_unchain_rows(verdicts)
    if not rows:
        return {"fp_count": 0, "written": 0, "place_ids": [],
                "writer_result": None}

    result = observation_writer(rows, admin_id)

    place_ids = [r["place_id"] for r in rows]
    if ptu_trigger:
        ptu_trigger(place_ids)

    return {
        "fp_count": len(rows),
        "written": getattr(result, "created", len(rows)),
        "place_ids": place_ids,
        "writer_result": result,
    }
