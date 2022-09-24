#!/usr/bin/env python

from typing import List
import functions_framework
from flask import Request
from cdp_backend.database import models as db_models
import fireo
from google.auth.credentials import AnonymousCredentials
from google.cloud.firestore import Client
from flask import jsonify


@functions_framework.http
def get_event_source_ids(request: Request):
    fireo.connection(
        client=Client(
            project="cdp-montana-legislature",
            credentials=AnonymousCredentials(),
        )
    )

    events_with_source_id = list(
        map(
            lambda e: {"event_id": e.id,
                       "external_source_id": e.external_source_id},
            _get_all_events(),
        )
    )

    response = jsonify(events_with_source_id)
    return response


def _get_all_events() -> List[db_models.Event]:
    return list(db_models.Event.collection.fetch())
