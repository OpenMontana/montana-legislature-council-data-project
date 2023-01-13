import unittest

from cdp_montana_legislature_backend.scraper import LAWS_2023_ROOT_URL, get_bills

class ScraperTestCase(unittest.TestCase):

    # TODO use betamax to record sessions
    def testGetBills(self):
        bills = get_bills(LAWS_2023_ROOT_URL)
        self.assertGreater(len(bills), 0)

if __name__ == '__main__':
    unittest.main()
