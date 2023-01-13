from betamax.fixtures import unittest

from cdp_montana_legislature_backend.scraper import LAWS_2023_ROOT_URL, get_bills


class ScraperTestCase(unittest.BetamaxTestCase):
    def testGetBills(self):
        bills = get_bills(self.session, LAWS_2023_ROOT_URL)
        self.assertGreater(len(bills), 0)
