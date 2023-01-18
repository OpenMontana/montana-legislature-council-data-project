from betamax.fixtures import unittest
from bs4 import BeautifulSoup
import logging

import cdp_montana_legislature_backend.scraper as scraper


class ScraperTestCase(unittest.BetamaxTestCase):
    def setUp(self):
        super().setUp()
        logging.disable(logging.CRITICAL)

    def test_get_laws_all_bills_html(self):
        try:
            scraper.get_laws_all_bills_html(self.session, scraper.LAWS_2023_ROOT_URL)
        except Exception as e:
            self.fail(f"Parser failed with {e}!")

    def test_get_active_bill_rows_returns_correct_number_of_rows_from_the_second_table(
        self,
    ):
        html = BeautifulSoup(
            # the second table here has two rows
            # the method will skip the first row so only one row is returned
            "<body><table><tr></tr></table><table><tr></tr><tr></tr></table><table><tr></tr><tr></tr><tr></tr></table></body>",
            features="html.parser",
        )
        bill_rows = scraper.get_active_bills_rows(html)
        self.assertEqual(1, len(bill_rows))

    def test_row_to_bill_not_tr_raises_valueerror(self):
        html = BeautifulSoup("<div></div>", features="html.parser")
        try:
            scraper.row_to_bill(html)
            self.fail("Expected exception")
        except ValueError:
            pass

    def test_row_to_bill_no_anchor_tag_raises_valueerror(self):
        html = BeautifulSoup(
            "<tr><td><b>sometext</b></td></tr>", features="html.parser"
        )
        try:
            scraper.row_to_bill(html)
            self.fail("Expected exception")
        except ValueError:
            pass

    def test_row_to_bill_returns_bill_with_expected_type_number(self):
        html = BeautifulSoup(
            '<tr>\n<td><a href="LAW0210W$BSIV.ActionQuery?P_BILL_NO1=1&P_BLTP_BILL_TYP_CD=HB&Z_ACTION=Find&P_SESS=20231">HB 1</a>&nbsp&nbsp&nbsp&nbsp&nbsp&nbsp<a href="http://leg.mt.gov/bills/2023/billhtml/HB0001.htm"><img src="http://laws.leg.mt.gov/images/html.png" BORDER=0, TITLE="Current Text in .HTML format" /></a>&nbsp&nbsp<a href="http://leg.mt.gov/bills/2023/billpdf/HB0001.pdf"><img src="http://laws.leg.mt.gov/images/pdf.png" BORDER=0, TITLE="Current Text in .PDF format" /></a></td>\n<td>LC0001</td>\n<td>|Llew  Jones&nbsp;(R) HD 18</td>\n<td>|(S) 3rd Reading Concurred</td>\n<td>01/17/2023</td>\n<td>Feed bill to fund 68th legislative session and prepare for 2025</td>\n</tr>',
            features="html.parser",
        )
        bill = scraper.row_to_bill(next(html.children))  # type: ignore
        self.assertEqual("HB 1", bill.type_number)

    def test_row_to_bill_returns_bill_with_expected_action_url(self):
        html = BeautifulSoup(
            '<tr>\n<td><a href="LAW0210W$BSIV.ActionQuery?P_BILL_NO1=1&P_BLTP_BILL_TYP_CD=HB&Z_ACTION=Find&P_SESS=20231">HB 1</a>&nbsp&nbsp&nbsp&nbsp&nbsp&nbsp<a href="http://leg.mt.gov/bills/2023/billhtml/HB0001.htm"><img src="http://laws.leg.mt.gov/images/html.png" BORDER=0, TITLE="Current Text in .HTML format" /></a>&nbsp&nbsp<a href="http://leg.mt.gov/bills/2023/billpdf/HB0001.pdf"><img src="http://laws.leg.mt.gov/images/pdf.png" BORDER=0, TITLE="Current Text in .PDF format" /></a></td>\n<td>LC0001</td>\n<td>|Llew  Jones&nbsp;(R) HD 18</td>\n<td>|(S) 3rd Reading Concurred</td>\n<td>01/17/2023</td>\n<td>Feed bill to fund 68th legislative session and prepare for 2025</td>\n</tr>',
            features="html.parser",
        )
        bill = scraper.row_to_bill(next(html.children))  # type: ignore
        self.assertEqual(
            "http://laws.leg.mt.gov/legprd/LAW0210W$BSIV.ActionQuery?P_BILL_NO1=1&P_BLTP_BILL_TYP_CD=HB&Z_ACTION=Find&P_SESS=20231",
            bill.get_bill_actions_url(),
        )

    def test_row_to_bill_returns_bill_with_expected_short_title(self):
        html = BeautifulSoup(
            '<tr>\n<td><a href="LAW0210W$BSIV.ActionQuery?P_BILL_NO1=1&P_BLTP_BILL_TYP_CD=HB&Z_ACTION=Find&P_SESS=20231">HB 1</a>&nbsp&nbsp&nbsp&nbsp&nbsp&nbsp<a href="http://leg.mt.gov/bills/2023/billhtml/HB0001.htm"><img src="http://laws.leg.mt.gov/images/html.png" BORDER=0, TITLE="Current Text in .HTML format" /></a>&nbsp&nbsp<a href="http://leg.mt.gov/bills/2023/billpdf/HB0001.pdf"><img src="http://laws.leg.mt.gov/images/pdf.png" BORDER=0, TITLE="Current Text in .PDF format" /></a></td>\n<td>LC0001</td>\n<td>|Llew  Jones&nbsp;(R) HD 18</td>\n<td>|(S) 3rd Reading Concurred</td>\n<td>01/17/2023</td>\n<td>Feed bill to fund 68th legislative session and prepare for 2025</td>\n</tr>',
            features="html.parser",
        )
        bill = scraper.row_to_bill(next(html.children))  # type: ignore
        self.assertEqual(
            "Feed bill to fund 68th legislative session and prepare for 2025",
            bill.short_title,
        )
