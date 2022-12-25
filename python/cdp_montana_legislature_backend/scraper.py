#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
from datetime import datetime, date
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

    # Set to False if you want to limit what you're scraping to only the bills listed in `key_bill_names`
    should_scrape_all_bills = False
    key_bill_names = ["HB 6"]
    from_dt = datetime(2021, 4, 20)
    to_dt = datetime(2021, 4, 27)
    
    # Start at the big table of all bills.
    bills_url_2021 = "http://laws.leg.mt.gov/legprd/LAW0217W$BAIV.return_all_bills?P_SESS=20211"
    # bills_url_2023 = "http://laws.leg.mt.gov/legprd/LAW0217W$BAIV.return_all_bills?P_SESS=20231"
    bills_html = requests.get(bills_url_2021).text
    parsed_bills_html = BeautifulSoup(bills_html, 'html.parser')
    bills_table = parsed_bills_html.find_all('table')[1]
    # Skip the first row because it's headings within a <tr>
    bills_table_rows = bills_table.find_all('tr')[1:]
    log.info(f"Found table with {len(bills_table_rows) - 1} rows.")

    # Store off the LAWS bill URLs for the bills of interest for the next step.
    bills_data = []
    for bill_row in bills_table_rows:
        bill_link = bill_row.find_all('a')[0]
        bill_type_number = bill_link.text
        bill_data = {}
        if should_scrape_all_bills or bill_type_number in key_bill_names:
            last_update_dt_str = (bill_row.find_all('td')[-2].text).split(';')[0]
            last_update_date = datetime.strptime(last_update_dt_str, "%m/%d/%Y").date()

            # Only try to scrape this bill if it has been updated between the from_dt and to_dt params passed to the scraper.
            is_bill_updated_after_specified_start = from_dt is None or last_update_date >= from_dt.date()
            is_bill_updated_before_specified_end = to_dt is None or last_update_date <= to_dt.date()
            if is_bill_updated_after_specified_start and is_bill_updated_before_specified_end:
                bill_data['bill_type_number'] = bill_type_number
                bill_data['description'] = bill_row.find_all('td')[-1].text
                bill_data['laws_bill_url'] = "http://laws.leg.mt.gov/legprd/" + bill_link['href']
                bills_data.append(bill_data)

    event_data = []
    # Go to each LAWS bill URL and find bill actions that have associated recordings.
    for bill_data in bills_data:
        # log.info(f"Starting scrape of {bill_data}")
        laws_bill_html = requests.get(bill_data['laws_bill_url']).text
        # We use regex search on the full html instead of going through BeautifulSoup due to "invalid" HTML returned by
        # the server that can't be parsed by BeautifulSoup.
        bill_rows_with_recordings = re.findall('.*sliq.*', laws_bill_html)
        for bill_row in bill_rows_with_recordings:
            parsed_bill_row = BeautifulSoup(bill_row, 'html.parser')
            bill_cells = parsed_bill_row.find_all('td')
            hearing_date_str = bill_cells[1].text
            hearing_date = datetime.strptime(hearing_date_str, "%m/%d/%Y").date()

            is_hearing_after_specified_start = from_dt is None or hearing_date >= from_dt.date()
            is_hearing_before_specified_end = to_dt is None or hearing_date <= to_dt.date()

            if is_hearing_after_specified_start and is_hearing_before_specified_end:
                sliq_links = bill_cells[-1].find_all('a', href=re.compile('sliq'))

                hearing_data = {}
                last_link_added = False
                # Of the recordings available for this action, prefer using the video over the audio if video exists.
                # If it doesn't exist, use the audio.
                for link in sliq_links:
                    sliq_link = link['href']
                    sliq_html = requests.get(sliq_link).text

                    media_info_regex = re.search('downloadMediaUrls = (.*);', sliq_html)
                    # No media is on the page as far as we are concerned
                    if media_info_regex is None:
                        continue
                        
                    media_info = media_info_regex.groups()[0]
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
                        # included yet, thus the video shouldn't be scraped on this pass? Do full scrape and see what happens
                        agenda_id = 'A' + parse_qs(parsed_url.query)['agendaId'][0]
                        agenda_index = [i for i, d in enumerate(event_info_json) if agenda_id in d.values()][0]
                        first_agenda_item_datetime_str = event_info_json[0]['startTime'].split('.', 1)[0]
                        first_agenda_item_time = datetime.strptime(first_agenda_item_datetime_str, '%Y-%m-%dT%H:%M:%S').time()
                        start_datetime_str = event_info_json[agenda_index]['startTime'].split('.', 1)[0]
                        start_datetime = datetime.strptime(start_datetime_str, '%Y-%m-%dT%H:%M:%S')
                        hearing_data['session_datetime'] = start_datetime

                        end_time = None
                        agenda_len = len(event_info_json)

                        # Occasionally the timestamps will be the same for various agenda items, i.e., the hearings for
                        # two different bills share the same timestamp. In the 2021 legislative session, out of 1312 bills,
                        # this only happened with 13 hearings. This logic jumps to the next timestamp if the one directly
                        # after the one the agenda item is targeting is the same, and keeps going until it finds a different
                        # timestamp.
                        for i in range(1, agenda_len + 1):
                            if agenda_len > agenda_index + i:
                                end_datetime_str = event_info_json[agenda_index + i]['startTime'].split('.', 1)[0]
                                end_time = datetime.strptime(end_datetime_str, '%Y-%m-%dT%H:%M:%S').time()

                            if end_time == start_datetime.time():
                                continue
                            else:
                                break

                        hearing_data['start_time'] = str(datetime.combine(date.min, start_datetime.time()) - datetime.combine(date.min, first_agenda_item_time))
                        if end_time is not None:
                            hearing_data['end_time'] = str(datetime.combine(date.min, end_time) - datetime.combine(date.min, first_agenda_item_time))

                        last_link_added = True

                event_data.append(hearing_data)
    
    def create_ingestion_model(e):
        try:
            return EventIngestionModel(
                body=Body(name=e['title']),
                sessions=[
                    Session(
                        video_uri=e['video_uri'],
                        video_start_time=e['start_time'],
                        video_end_time=e['end_time'],
                        session_datetime=e['session_datetime'],
                        session_index=0,
                        external_source_id=e['external_source_id']
                    ),
                ],
            )
        # noqa: F841,W504
        except Exception as exception:
            log.info("===================================================\n\n\n" + 
                "Got exception:\n\n {exception} \n\nFor this event:\n\n {e}\n\n\n" + 
                "===================================================")

    events = list(map(create_ingestion_model, event_data))

    print(f"Events: {events}")

    return events


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

    events = get_events(from_dt, to_dt)
    log.info(f"Scraped events: {events}")
