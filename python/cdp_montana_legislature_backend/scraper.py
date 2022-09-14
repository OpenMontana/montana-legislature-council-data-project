#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
from datetime import datetime
from typing import List
from bs4 import BeautifulSoup
import requests
import re
import json

from urllib.parse import urlparse, parse_qs
from cdp_backend.pipeline.ingestion_models import Body
from cdp_backend.pipeline.ingestion_models import EventIngestionModel
from cdp_backend.pipeline.ingestion_models import Session

# region logging

log = logging.getLogger("cdp_montana_legislature_scraper")
ch = logging.StreamHandler()
ch.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)
log.addHandler(ch)

# endregion

###############################################################################


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
    As the implimenter of the get_events function, you can choose to ignore
    the from_dt and to_dt parameters. However, they are useful for manually
    kicking off pipelines from GitHub Actions UI.
    """
    log.info("Starting MT Legislature Scraper")

    # TODO: Read key bills from config or Capitol Tracker JSON
    key_bill_names = ["HB 1"]
    
    # Start at the big table of all bills from the 2021 session.
    bills_url_2021 = "http://laws.leg.mt.gov/legprd/LAW0217W$BAIV.return_all_bills?P_SESS=20211"
    bills_html = requests.get(bills_url_2021).text
    parsed_bills_html = BeautifulSoup(bills_html, 'html.parser')
    bills_table = parsed_bills_html.find_all('table')[1]
    # Skip the first row because it's headings within a <tr>
    bills_table_rows = bills_table.find_all('tr')[1:]
    print(f"Found table with {len(bills_table_rows) - 1} rows.")

    # Of all the bills, narrow down to only the key bills and store off the LAWS bill URL for the next step.
    key_bills_data = []
    for bill_row in bills_table_rows:
        bill_link = bill_row.find_all('a')[0]
        bill_type_number = bill_link.text
        bill_data = {}
        if bill_type_number in key_bill_names:
            bill_data['bill_type_number'] = bill_type_number
            bill_data['description'] = bill_row.find_all('td')[-1].text
            bill_data['laws_bill_url'] = "http://laws.leg.mt.gov/legprd/" + bill_link['href']
            key_bills_data.append(bill_data)

    print(f"Found key bills: {key_bills_data}")

    event_data = []
    # Go to each LAWS bill URL and find bill actions that have associated recordings.
    for bill_data in key_bills_data:
        laws_bill_html = requests.get(bill_data['laws_bill_url']).text
        # We use regex search on the full html instead of going through BeautifulSoup due to "invalid" HTML returned by
        # the server that can't be parsed by BeautifulSoup.
        bill_rows_with_recordings = re.findall('.*sliq.*', laws_bill_html)
        for bill_row in bill_rows_with_recordings:
            # TODO: Use from_dt and to_dt to filter bill actions within date range
            parsed_bill_row = BeautifulSoup(bill_row, 'html.parser')
            bill_cells = parsed_bill_row.find_all('td')
            sliq_links = bill_cells[-1].find_all('a', href=re.compile('sliq'))

            hearing_data = {}
            last_link_added = False
            # Of the recordings available for this action, prefer using the video over the audio if video exists.
            # If it doesn't exist, use the audio.
            for link in sliq_links:
                sliq_link = link['href']
                sliq_html = requests.get(sliq_link).text

                media_info = re.search('downloadMediaUrls = (.*);', sliq_html).groups()[0]
                parsed_media_info = json.loads(media_info)[0]
                is_video = parsed_media_info['AudioOnly'] is False

                if not last_link_added or is_video:
                    bill_action = bill_cells[0].text
                    title = bill_data['bill_type_number'] + ' - ' + bill_action
                    committee = bill_cells[-1].text.strip()
                    if not committee == '':
                        title += ' - ' + committee
                    hearing_data['title'] = title
                    hearing_data['video_uri'] = parsed_media_info['Url']
                    # The `external_source_id` will be used by the Capitol Tracker frontend to correlate the bill to
                    # the CDP event ID.
                    hearing_data['external_source_id'] = sliq_link

                    # Get the start and end time positions for the videos
                    event_info_text = re.search('AgendaTree:(.*),', sliq_html).groups()[0]
                    event_info_json = json.loads(event_info_text)
                    parsed_url = urlparse(sliq_link)
                    # TODO: Handle if this isn't in the query? Does that always mean that the timestamp hasn't been
                    # included yet, thus the video shouldn't be scraped on this pass? 
                    agenda_id = 'A' + parse_qs(parsed_url.query)['agendaId'][0]
                    agenda_index = [i for i, d in enumerate(event_info_json) if agenda_id in d.values()][0]
                    start_time = event_info_json[agenda_index]['startTime']

                    end_time = None
                    if len(event_info_json) > agenda_index + 1:
                        end_time = event_info_json[agenda_index + 1]['startTime']

                    hearing_data['start_time'] = start_time
                    if end_time is not None:
                        hearing_data['end_time'] = end_time

                    last_link_added = True

            event_data.append(hearing_data)
    
    # TODO: Add start_time/end_time video timestamps to this when possible in CDP to transcribe only part of a video.
    def create_ingestion_model(e):
        return EventIngestionModel(
            body=Body(name=e['title']),
            sessions=[
                Session(
                    video_uri=e['video_uri'],
                    # TODO: Scrape correct datetime for session
                    session_datetime=datetime.now(),
                    session_index=0,
                    external_source_id=e['external_source_id']
                ),
            ],
        )

    events = list(map(create_ingestion_model, event_data))

    # TODO: Return events when we're ready to run the scraper
    return []


if __name__ == "__main__":

    log.setLevel(logging.DEBUG)

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

    args = parser.parse_args()

    from_dt = datetime.min
    to_dt = datetime.max

    from dateutil import parser

    if args.from_dt is not None:
        log.debug(f"Parsing from_dt={args.from_dt} as datetime")
        from_dt = parser.isoparse(args.from_dt)

    if args.to_dt is not None:
        log.debug(f"Parsing to_dt={args.to_dt} as datetime")
        to_dt = parser.isoparse(args.to_dt)

    log.debug(f"Using arguments: from_dt={from_dt}, to_dt={to_dt}")

    events = get_events(args.from_dt, args.to_dt)
    log.info(f"Scraped events: {events}")
