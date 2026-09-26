"""`claims.json` against the files it describes. See tools/docclaims.py.

Every count this project states about itself is declared in the ledger with a
`derive` rule that reads the number out of the source - a test count by parsing
the test files, a constant by capturing it. So a count that moves without its
prose fails here, on the runner, importing nothing from the project.

No number is written into this file. A test that hard-codes the figure it
guards is a second copy of the claim, which is the defect one level up.
"""

import copy
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import docclaims as claims  # noqa: E402  (vendored docclaims; see TheVendoredCopy)

LEDGER = ROOT / "claims.json"


class TheLedger(unittest.TestCase):

    def test_every_claim_holds(self):
        _ledger, findings = claims.verify(ROOT)
        fatal = [f.line() for f in findings if f.fatal]
        self.assertEqual(fatal, [], "\n".join(fatal))

    def test_a_count_that_moved_is_caught(self):
        # A checker that cannot fail is the defect it was written to find, so
        # stage the drift: the source says one thing, the ledger another.
        derived = [c for c in claims.load(LEDGER) if c.get("derive")]
        self.assertTrue(derived, "the ledger reads nothing from source")
        moved = copy.deepcopy(derived[0])
        moved["value"] = "not " + moved["value"]
        found = claims.check_derived([moved], ROOT)
        self.assertTrue(any(f.fatal for f in found), found)



class TheVendoredCopy(unittest.TestCase):
    """`tools/docclaims.py` is the docclaims v0.3.3 release, byte for byte.

    A vendored file edited in place is a fork nobody decided to make, and
    the next upgrade silently discards the edit. Upgrading is copying the
    new release over it and changing both constants here.
    """

    VERSION = "0.3.3"
    SHA256 = "b5e8f0c4d9fc0bdcee5a479e937e59adf225591b7c2eb6d723e06ad3c0ff017b"

    def test_it_is_the_release_it_claims_to_be(self):
        import hashlib
        path = pathlib.Path(claims.__file__)
        self.assertEqual(claims.__version__, self.VERSION)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                         self.SHA256,
                         "tools/docclaims.py differs from the v%s release; "
                         "fix docclaims upstream, not this copy" % self.VERSION)

if __name__ == "__main__":
    unittest.main()
