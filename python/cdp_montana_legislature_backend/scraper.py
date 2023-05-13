#!/usr/bin/env python
# -*- coding: utf-8 -*-
# flake8: noqa

from dataclasses import dataclass
import logging
from datetime import datetime, date
from typing import List
from bs4 import BeautifulSoup, Tag
import requests
import re
import json

from urllib.parse import urlparse, parse_qs
from cdp_backend.pipeline.ingestion_models import Body
from cdp_backend.pipeline.ingestion_models import EventIngestionModel
from cdp_backend.pipeline.ingestion_models import Session

# MT Legislature 2023 Regular Session
LAWS_2023_ROOT_URL = (
    "https://laws.leg.mt.gov/legprd/LAW0217W$BAIV.return_all_bills?P_SESS=20231"
)


@dataclass
class Bill:
    type_number: str
    short_title: str
    action_url_path: str

    def get_bill_actions_url(self) -> str:
        return f"https://laws.leg.mt.gov/legprd/{self.action_url_path}"


def row_to_bill(row: Tag) -> Bill:
    """Convert a table row (as a Tag) in the LAWS search results bills table to a Bill."""

    try:
        assert row.name == "tr"
    except AssertionError as e:
        logging.error(f"Tag: {row} is not a table row!")
        raise ValueError(e)

    bill_link = row.find_next("a")

    if type(bill_link) is not Tag:
        logging.error(f"Did not find an <a> in tag: {row}!")
        raise ValueError

    # the inner HTML of the anchor tag contains the bill title, e.g. "HB 2"
    bill_type_number = bill_link.text
    # the href contains a relative path to the actions page for this bill, e.g.
    # LAW0210W$BSIV.ActionQuery?P_BILL_NO1=2&P_BLTP_BILL_TYP_CD=HB&Z_ACTION=Find&P_SESS=20231
    # because the url path is relative in this tag we must prefix it with the LAWS application
    bill_action_url_path = bill_link.attrs["href"]
    # the last <td> in this row contains a short description of the bill, e.g.
    # "General Appropriations Act"
    short_title = row.find_all("td")[-1].text

    bill = Bill(bill_type_number, short_title, bill_action_url_path)
    logging.debug(f"Found bill: {bill}.")
    return bill


def get_active_bills_rows(laws_all_bills_html: BeautifulSoup) -> List[Tag]:
    # The first table on the LAWS Bill Search Result page is in the header. The second table contains
    # the listing of the active bills.
    all_bills_table: Tag = laws_all_bills_html.find_all("table")[1]
    # This <table> doesn't have a <th>, so we get all <tr> and skip the first row
    # which contains the column headers.
    all_bills_table_rows: List[Tag] = all_bills_table.find_all("tr")[1:]
    logging.debug(f"Found {len(all_bills_table_rows)} bills.")
    return all_bills_table_rows


def get_laws_all_bills_html(s: requests.Session, laws_root_url: str) -> BeautifulSoup:
    """Starting from the root url, request the page and hand-off to BeautifulSoup for parsing."""
    logging.info(f"Loading bills from {laws_root_url}…")
    laws_all_bills_html = BeautifulSoup(
        s.get(laws_root_url).text, features="html.parser"
    )
    return laws_all_bills_html


def get_events(
    from_dt: datetime,
    to_dt: datetime,
    **kwargs,
) -> List[EventIngestionModel]:
    """
    Get all events for the provided timespan.

    Parameters
    ----------
    from_dt: datetime
        Datetime to start event gather from.
    to_dt: datetime
        Datetime to end event gather at.

    Returns
    -------
    events: List[EventIngestionModel]
        All events gathered that occured in the provided time range.

    Notes
    -----
    As the implementer of the get_events function, you can choose to ignore
    the from_dt and to_dt parameters. However, they are useful for manually
    kicking off pipelines from GitHub Actions UI.
    """

    logging.info("Starting MT Legislature Scraper.")

    with requests.Session() as s:
        laws_all_bills_html = get_laws_all_bills_html(s, LAWS_2023_ROOT_URL)
        active_bill_rows = get_active_bills_rows(laws_all_bills_html)
        bills = [row_to_bill(t) for t in active_bill_rows]

    event_data = []
    # Go to each LAWS bill URL and find bill actions that have associated recordings.
    for bill in bills:
        logging.info(f"[{bill.type_number}] Starting ingestion.")

        logging.info(
            f"[{bill.type_number}] Getting LAWS bill url: {bill.get_bill_actions_url()}..."
        )
        laws_bill_html = requests.get(bill.get_bill_actions_url()).text
        # We use regex search on the full html instead of going through BeautifulSoup due to "invalid" HTML returned by
        # the server that can't be parsed by BeautifulSoup.
        bill_rows_with_recordings = re.findall(".*sliq.*", laws_bill_html)

        if not bill_rows_with_recordings:
            logging.info(
                f"[{bill.type_number}] No bills found with recordings, no events will be ingested."
            )

        for bill_row in bill_rows_with_recordings:
            parsed_bill_row = BeautifulSoup(bill_row, "html.parser")
            bill_cells = parsed_bill_row.find_all("td")
            hearing_date_str = bill_cells[1].text
            hearing_date = datetime.strptime(hearing_date_str, "%m/%d/%Y").date()

            is_hearing_after_specified_start = (
                from_dt is None or hearing_date >= from_dt.date()
            )
            is_hearing_before_specified_end = (
                to_dt is None or hearing_date <= to_dt.date()
            )

            if is_hearing_after_specified_start and is_hearing_before_specified_end:
                sliq_links = bill_cells[-1].find_all("a", href=re.compile("sliq"))
                if not sliq_links:
                    logging.info(
                        f"[{bill.type_number}] No sliq_links found, no events will be ingested."
                    )

                hearing_data = {}
                last_link_added = False
                # Of the recordings available for this action, prefer using the video over the audio if video exists.
                # If it doesn't exist, use the audio.
                for link in sliq_links:
                    sliq_link = link["href"]
                    logging.info(
                        f"[{bill.type_number}] Getting page from: {sliq_link}..."
                    )
                    sliq_html = requests.get(sliq_link).text

                    media_info_regex = re.search("downloadMediaUrls = (.*);", sliq_html)
                    # No media is on the page as far as we are concerned
                    if media_info_regex is None:
                        continue

                    media_info = media_info_regex.groups()[0]
                    parsed_media_info = json.loads(media_info)[0]
                    is_video = parsed_media_info["AudioOnly"] is False

                    if not last_link_added or is_video:
                        bill_action = bill_cells[0].text
                        title = bill.type_number + " - " + bill_action
                        committee = bill_cells[-1].text.strip()
                        if not committee == "":
                            title += " - " + committee
                        hearing_data["title"] = title
                        hearing_data["video_uri"] = parsed_media_info["Url"]
                        # The `external_source_id` will be used by the Capitol Tracker frontend to correlate the bill to
                        # the CDP event ID.
                        hearing_data["external_source_id"] = sliq_link

                        # Get the start and end time positions for the videos
                        event_info_text = re.search(
                            "AgendaTree:(.*),", sliq_html
                        ).groups()[0]
                        event_info_json = json.loads(event_info_text)
                        parsed_url = urlparse(sliq_link)
                        # If there is no `agendaId` in the url, we are assuming timestamps haven't been added yet. For 10 more days,
                        # we will continue to try to scrape this video again until there are timestamps.
                        if "agendaId" in parse_qs(parsed_url.query):
                            agenda_id = "A" + parse_qs(parsed_url.query)["agendaId"][0]
                            agenda_indices = [
                                i
                                for i, d in enumerate(event_info_json)
                                if agenda_id in d.values()
                            ]
                            # Even when agendaId is present in the query params it might not be present
                            # in the AgendaTree parsed from the SLIQ page. In that case, we will skip over
                            # this bill row since we don't know a time-range to constrain the transcript generation
                            if len(agenda_indices) > 0:
                                agenda_index = agenda_indices[0]
                            else:
                                logging.warn(
                                    f"agenda_id: {agenda_id} not found in AgendaTree from url: {sliq_link}."
                                )
                                continue

                            logging.debug(
                                f"[{bill.type_number}] agendaId={agenda_id}, agenda_index={agenda_index}"
                            )
                            logging.debug(
                                f"[{bill.type_number}] event_info_json={event_info_json}"
                            )

                            # the first agenda item in the tree might not contain a timestamp so we need to iterate
                            # the agenda tree until we find the first occurence of startTime
                            first_agenda_item_datetime_str = next(
                                a["startTime"]
                                for a in event_info_json
                                if a["startTime"]
                            ).split(".", 1)[0]
                            first_agenda_item_time = datetime.strptime(
                                first_agenda_item_datetime_str, "%Y-%m-%dT%H:%M:%S"
                            ).time()

                            start_datetime_str = event_info_json[agenda_index][
                                "startTime"
                            ].split(".", 1)[0]
                            start_datetime = datetime.strptime(
                                start_datetime_str, "%Y-%m-%dT%H:%M:%S"
                            )
                            hearing_data["session_datetime"] = start_datetime

                            end_time = None
                            agenda_len = len(event_info_json)

                            # Occasionally the timestamps will be the same for various agenda items, i.e., the hearings for
                            # two different bills share the same timestamp. In the 2021 legislative session, out of 1312 bills,
                            # this only happened with 13 hearings. This loggingic jumps to the next timestamp if the one directly
                            # after the one the agenda item is targeting is the same, and keeps going until it finds a different
                            # timestamp.
                            for i in range(1, agenda_len + 1):
                                if agenda_len > agenda_index + i:
                                    end_datetime_str = event_info_json[
                                        agenda_index + i
                                    ]["startTime"].split(".", 1)[0]
                                    end_time = datetime.strptime(
                                        end_datetime_str, "%Y-%m-%dT%H:%M:%S"
                                    ).time()

                                if end_time == start_datetime.time():
                                    continue
                                else:
                                    break

                            hearing_data["start_time"] = str(
                                datetime.combine(date.min, start_datetime.time())
                                - datetime.combine(date.min, first_agenda_item_time)
                            )
                            if end_time is not None:
                                hearing_data["end_time"] = str(
                                    datetime.combine(date.min, end_time)
                                    - datetime.combine(date.min, first_agenda_item_time)
                                )

                            last_link_added = True
                            event_data.append(hearing_data)
                        else:
                            logging.info(
                                f"[{bill.type_number}] agendaId not found in {sliq_link}, no events will be ingested."
                            )
            else:
                logging.info(
                    f"[{bill.type_number}] No hearing in {from_dt} and {to_dt}, no events will be ingested."
                )

    def create_ingestion_model(e):
        try:
            return EventIngestionModel(
                body=Body(name=e["title"]),
                sessions=[
                    Session(
                        video_uri=e["video_uri"],
                        video_start_time=e["start_time"],
                        video_end_time=e["end_time"],
                        session_datetime=e["session_datetime"],
                        session_index=0,
                    ),
                ],
                external_source_id=e["external_source_id"],
            )
        except Exception as exc:
            logging.warning(
                f"Unable to format event data to EventIngestionModel from: {e}",
                exc_info=exc,
            )

    events = [
        event for event in map(create_ingestion_model, event_data) if event is not None
    ]
    logging.info(f"Found {len(events)} to be ingested.")

    for i, e in enumerate(events):
        logging.info(f"{i}: {e.to_json(indent=2)}")

    return events


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scape events from MT Legislature")
    parser.add_argument(
        "-f",
        "--from_dt",
        help=(
            "An ISO-8601 timestamp used as the minimum timestamp for gathering"
            " events. If not set datetime.min is used."
        ),
    )
    parser.add_argument(
        "-t",
        "--to_dt",
        help=(
            "An ISO-8601 timestamp used as the maximum timestamp for gathering"
            " events. If not set datetime.max is used."
        ),
    )

    parser.add_argument(
        "--log", help="Sets the logging level, e.g. INFO, DEBUG; see logging module."
    )

    args = parser.parse_args()

    # set up logging
    loglevel = args.log
    numeric_level = getattr(logging, loglevel.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError("Invalid log level: %s" % loglevel)
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=numeric_level,
    )

    from_dt = datetime.min
    to_dt = datetime.max

    from dateutil import parser

    if args.from_dt is not None:
        logging.debug(f"Parsing from_dt={args.from_dt} as datetime")
        from_dt = parser.isoparse(args.from_dt)

    if args.to_dt is not None:
        logging.debug(f"Parsing to_dt={args.to_dt} as datetime")
        to_dt = parser.isoparse(args.to_dt)

    logging.debug(f"Using arguments: from_dt={from_dt}, to_dt={to_dt}")

    get_events(from_dt, to_dt)
