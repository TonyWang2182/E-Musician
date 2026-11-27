"""Device version/type/parameter drift must make operations unavailable."""
import unittest
from copy import deepcopy
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / "scripts"))
from music_agent.native_catalog import NativeCatalogError, validate_effect_catalog, validate_instrument_catalog
from test_music_agent_native_effects import fake_effect_catalog, fake_instrument_catalog

class NativeCatalogTests(unittest.TestCase):
    def test_matching_catalogue(self):
        self.assertTrue(validate_effect_catalog(fake_effect_catalog()))

    def test_future_unmapped_type_or_parameter_is_rejected(self):
        for mutate in (lambda c:c["types"].append({"type":"future","bands":0,"readable":True,"writable":True,"parameters":[]}),
                       lambda c:c["types"][0]["parameters"].append({"name":"future","kind":"number","minimum":0,"maximum":1,"per_band":False}),
                       lambda c:c["types"].pop(),
                       lambda c:c["types"][0]["parameters"][0].update(per_band=False),
                       lambda c:c.update(version=2)):
            value=deepcopy(fake_effect_catalog());mutate(value)
            with self.subTest(value=value), self.assertRaises(NativeCatalogError): validate_effect_catalog(value)

    def test_missing_host_catalogue_fails_closed(self):
        with self.assertRaisesRegex(NativeCatalogError,"matching versions"):
            validate_effect_catalog(None)

    def test_instrument_capabilities_and_incompatible_changes(self):
        self.assertTrue(validate_instrument_catalog(fake_instrument_catalog()))
        for mutate in (lambda c:c["types"].append({"type":"new_synth","actions":[]}),
                       lambda c:c["types"][0].update(model_can_assign_path=True),
                       lambda c:c["types"][0]["actions"][0]["parameters"][0].update(maximum=127),
                       lambda c:c["types"][0].update(single_action=False)):
            value=deepcopy(fake_instrument_catalog());mutate(value)
            with self.subTest(value=value),self.assertRaises(NativeCatalogError):validate_instrument_catalog(value)

if __name__ == "__main__": unittest.main()
