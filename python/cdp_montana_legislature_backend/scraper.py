#!/usr/bin/env python
# -*- coding: utf-8 -*-

from datetime import datetime
from typing import List
from bs4 import BeautifulSoup
import requests
import re
import json

from cdp_backend.pipeline.ingestion_models import EventIngestionModel

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
    As the implimenter of the get_events function, you can choose to ignore the from_dt
    and to_dt parameters. However, they are useful for manually kicking off pipelines
    from GitHub Actions UI.
    """

    # TODO Read key bills from config
    key_bills = ["HB 1"]
    
    bills_table_url = "http://laws.leg.mt.gov/legprd/LAW0217W$BAIV.return_all_bills?P_SESS=20211"
    print(f"Requesting {bills_table_url}...")
    bills_html = requests.get(bills_table_url).text

    print(f"Parsing HTML")
    soup = BeautifulSoup(bills_html, 'html.parser')
    bills_table = soup.find_all('table')[1]
    bills_table_data = bills_table.find_all('tr')
    print(f"Found table with {len(bills_table_data) - 1} rows.")

    #only key bills
    filtered_bills = []
    for bill_row in bills_table_data[1:]:
        bill_anchor = bill_row.find_all('a')[0]
        bill_name = bill_anchor.text
        bill = {}
        if bill_name in key_bills:
            bill_data = bill_row.find_all('td')
            bill['bill_type_number'] = bill_name
            bill['actions_url'] = "http://laws.leg.mt.gov/legprd/" + bill_anchor['href']
            bill['title'] = bill_data[len(bill_data) - 1].text
            filtered_bills.append(bill)

    print(f"Found key bills: {filtered_bills}")

    for fbill in filtered_bills:
        print(fbill['actions_url'])
        bill_actions_html = requests.get(fbill['actions_url']).text
        bill_rows_with_recordings = re.findall('.*sliq.*', bill_actions_html)
        for action_row in bill_rows_with_recordings:
            # TODO use from_dt and to_dt to filter bill actions
            soup = BeautifulSoup(action_row, 'html.parser')
            recording_links = soup.find_all('td')[-1].find_all('a')
            sliq_links = [ link for link in recording_links if "sliq" in link['href'] ]
            # TODO: Prefer video over audio if both exist
            recording_link = sliq_links[0]['href']
            print(f"recording_link={recording_link}")
            fbill['external_source_id'] = recording_link
            sliq_html = requests.get(recording_link).text
            media_urls_text = re.search('downloadMediaUrls = (.*);', sliq_html).groups()[0]
            media_urls_json = json.loads(media_urls_text)
            fbill['mp4_recording_url'] = media_urls_json 

            event_info_text = re.search('EventInfo:(.*),', sliq_html).groups()[0]
            event_info_json = json.loads(event_info_text)

            # TODO grab timestamp info and set to new metadata for Chris' CDP backend change to handle subset of video
    
    # TODO create event ingestion model

    return []
