#!/usr/bin/python

import unittest
import sys
import os

import ParsingTests

class UnorderedListTests(ParsingTests.ParsingTest):
    def testWellFormedList(self):
        return self.runParsingTest("unordered-wellformed")

    def testBadlyFormedList(self):
        return self.runParsingTest("unordered-badlyformed")

def suite():
    suite = unittest.TestSuite()
    suite.addTest(UnorderedListTests("testWellFormedList"))
    suite.addTest(UnorderedListTests("testBadlyFormedList"))
    return suite

if __name__ == "__main__":
    unittest.main()
