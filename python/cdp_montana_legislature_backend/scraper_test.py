import unittest

class ScraperTestCase(unittest.TestCase):

    @unittest.skip("fixme")
    def test(self):
        self.assertFalse(True)

    def testSkip(self):
        self.assertTrue(True)

if __name__ == '__main__':
    unittest.main()
