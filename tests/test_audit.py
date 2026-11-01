import ast
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from speaker_verification_claim_audit import phrases
from speaker_verification_claim_audit.audit import audit, claims, evidence, main


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def put(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')

    def run_cli(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            status = main([str(self.root), *args])
        return status, output.getvalue()

    def test_phrase_oracle(self):
        tree = ast.parse(Path(phrases.__file__).read_text())
        values = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)}
        self.assertEqual(values["VERIFY"], ('speaker verification', 'verifies speaker identity', 'verifies the speaker', 'verify speaker identity', 'speaker identification', 'identifies the speaker', 'identifies speakers', 'speaker recognition', 'recognizes the speaker', 'recognises the speaker', 'voice verification', 'verifies voice identity', 'voice identification', 'identifies the voice', 'voice authentication', 'authenticates the speaker', 'speaker authentication', 'voice biometric verification', 'voice biometrics', 'matches the speaker', 'matches voice', 'voice matching', 'confirms speaker identity', 'confirms the speaker', 'checks speaker identity', 'speaker identity verification', 'speaker identity check', 'verifies who is speaking', 'identifies who is speaking', 'knows who is speaking', 'enrolled speaker verification', 'compares voiceprints', 'voiceprint matching', 'voiceprint verification', 'matches voiceprints', 'identifies a speaker', 'verifies a speaker', 'speaker match', 'voice match', 'speaker identity confirmation'))
        self.assertEqual(values["NOVERIFY"], ('no speaker verification', 'does not verify speaker identity', 'without speaker verification', 'no speaker identification', 'does not identify the speaker', 'without speaker identification', 'no voice verification', 'does not verify voice identity', 'without voice verification', 'speaker verification not supported', 'does not support speaker verification', 'no voice authentication', 'does not authenticate the speaker', 'without voice authentication', 'cannot verify the speaker', 'never verifies the speaker', 'no speaker recognition', 'does not recognize the speaker', 'cannot identify the speaker', 'no voiceprint matching', 'does not match voiceprints', 'without speaker recognition', 'cannot verify speaker identity', 'no voice biometric verification'))

    def test_bad_claim(self):
        self.put('README.md', 'speaker verification')
        code, output = self.run_cli('--json')
        self.assertEqual(code, 2)
        result = json.loads(output)
        self.assertEqual(result['verdict'], 'FAIL')
        self.assertEqual(result['findings'], [{'id': 'documented-speaker-verification-claim-false', 'severity': 'HIGH', 'message': 'Documentation promises an operation absent from production source.'}])

    def test_good(self):
        self.put('README.md', 'speaker verification')
        self.put('app.py', 'engine.verify_files(a, b)')
        self.assertEqual(self.run_cli()[0], 0)
        self.assertEqual(audit(self.root)['verdict'], 'PASS')

    def test_denial(self):
        self.put('README.md', 'no speaker verification')
        self.put('app.py', 'engine.verify_files(a, b)')
        self.assertEqual(self.run_cli()[0], 2)
        self.assertEqual(audit(self.root)['findings'][0]['id'], 'documented-no-speaker-verification-claim-false')

    def test_no_source_denial(self):
        self.put('README.md', 'no speaker verification')
        self.assertEqual(audit(self.root)['verdict'], 'PASS')

    def test_no_claim(self):
        self.put('app.py', 'engine.verify_files(a, b)')
        self.assertEqual(audit(self.root)['verdict'], 'PASS')

    def test_test_only(self):
        self.put('README.md', 'speaker verification')
        self.put('tests/probe.py', 'engine.verify_files(a, b)')
        self.assertEqual(audit(self.root)['findings'][0]['severity'], 'MEDIUM')
        self.assertEqual(self.run_cli()[0], 0)
        self.assertEqual(self.run_cli('--fail-on', 'MEDIUM')[0], 2)

    def test_split_modules(self):
        self.put('README.md', 'speaker verification')
        self.put('a.py', 'VoiceEncoder()')
        self.put('b.py', 'encoder.embed_utterance(audio)')
        self.assertEqual(self.run_cli()[0], 2)

    def test_symlinks(self):
        self.put('README.md', 'speaker verification')
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / 'real.py').write_text('engine.verify_files(a,b)')
            (self.root / 'linked.py').symlink_to(target / 'real.py')
            (self.root / 'linked').symlink_to(target, target_is_directory=True)
            self.assertEqual(self.run_cli()[0], 2)

    def test_ignore(self):
        self.put('README.md', 'speaker verification')
        self.put('src/app.py', 'engine.verify_files(a,b)')
        self.assertEqual(self.run_cli('--ignore', 'src')[0], 2)

    def test_docs_selection(self):
        self.put('other.md', 'speaker verification')
        self.assertEqual(self.run_cli()[0], 0)
        self.put('nested/docs/page.md', 'speaker verification')
        self.assertEqual(self.run_cli()[0], 2)

    def test_errors(self):
        self.assertEqual(main(['/nonexistent/audit-root']), 1)
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                main(['--invalid'])
        self.assertEqual(caught.exception.code, 1)

    def test_module_entry(self):
        result = subprocess.run([sys.executable, '-m', 'speaker_verification_claim_audit', '--version'], capture_output=True, text=True)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, '0.1.0'))

    def test_console_declaration(self):
        root = Path(__file__).resolve().parents[1]
        project = root / 'pyproject.toml'
        if project.exists():
            self.assertIn('speaker-verification-claim-audit = "speaker_verification_claim_audit.audit:main"', project.read_text())

    def test_version(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            with self.assertRaises(SystemExit) as caught:
                main(['--version'])
        self.assertEqual(caught.exception.code, 0)
        self.assertEqual(out.getvalue().strip(), '0.1.0')

    def test_evidence_00(self):
        self.assertTrue(evidence('s.verify_files(a,b)'))

    def test_evidence_01(self):
        self.assertTrue(evidence('s.verify_batch(a,b)'))

    def test_evidence_02(self):
        self.assertTrue(evidence('VoiceEncoder(); e.embed_utterance(a)'))

    def test_evidence_03(self):
        self.assertTrue(evidence('resemblyzer.VoiceEncoder(); e.embed_utterance(a)'))

    def test_evidence_04(self):
        self.assertTrue(evidence('Pipeline.from_pretrained("pyannote/speaker-verification")'))

    def test_evidence_05(self):
        self.assertTrue(evidence('p.from_pretrained(model="SPEAKER-VERIFICATION")'))

    def test_evidence_06(self):
        self.assertTrue(evidence('s.verify_speaker(a)'))

    def test_evidence_07(self):
        self.assertTrue(evidence('s.identify_speaker(a)'))

    def test_evidence_08(self):
        self.assertTrue(evidence('from resemblyzer import VoiceEncoder as VE\nVE(); e.embed_utterance(a)'))

    def test_evidence_09(self):
        self.assertTrue(evidence('import resemblyzer as r\nr.VoiceEncoder(); e.embed_utterance(a)'))

    def test_evidence_10(self):
        self.assertTrue(evidence('from speechbrain import verify_files as vf\nvf(a,b)'))

    def test_non_evidence_00(self):
        self.assertFalse(evidence('import speechbrain, resemblyzer, pyannote'))

    def test_non_evidence_01(self):
        self.assertFalse(evidence('w.transcribe(a)'))

    def test_non_evidence_02(self):
        self.assertFalse(evidence('r.recognize_google(a)'))

    def test_non_evidence_03(self):
        self.assertFalse(evidence('pipeline("automatic-speech-recognition")'))

    def test_non_evidence_04(self):
        self.assertFalse(evidence('Pipeline.from_pretrained("speaker-diarization")'))

    def test_non_evidence_05(self):
        self.assertFalse(evidence('s.diarize(a)'))

    def test_non_evidence_06(self):
        self.assertFalse(evidence('vad.is_speech(a)'))

    def test_non_evidence_07(self):
        self.assertFalse(evidence('get_speech_timestamps(a)'))

    def test_non_evidence_08(self):
        self.assertFalse(evidence('n.reduce_noise(a)'))

    def test_non_evidence_09(self):
        self.assertFalse(evidence('df.enhance(a)'))

    def test_non_evidence_10(self):
        self.assertFalse(evidence('s.suppress_noise(a)'))

    def test_non_evidence_11(self):
        self.assertFalse(evidence('s.remove_noise(a)'))

    def test_non_evidence_12(self):
        self.assertFalse(evidence('mic.record(a)'))

    def test_non_evidence_13(self):
        self.assertFalse(evidence('audio.play(a)'))

    def test_non_evidence_14(self):
        self.assertFalse(evidence('engine.say(a)'))

    def test_non_evidence_15(self):
        self.assertFalse(evidence('gTTS(a).save(a)'))

    def test_non_evidence_16(self):
        self.assertFalse(evidence('edge_tts.Communicate(a)'))

    def test_non_evidence_17(self):
        self.assertFalse(evidence('e.embed_utterance(a)'))

    def test_non_evidence_18(self):
        self.assertFalse(evidence('VoiceEncoder()'))

    def test_non_evidence_19(self):
        self.assertFalse(evidence('cosine_similarity(a,b)'))

    def test_non_evidence_20(self):
        self.assertFalse(evidence('cluster.fit(a)'))

    def test_non_evidence_21(self):
        self.assertFalse(evidence('s.detect_language(a)'))

    def test_non_evidence_22(self):
        self.assertFalse(evidence('"speaker-verification speechbrain"'))

    def test_non_evidence_23(self):
        self.assertFalse(evidence('subprocess.run(["verify_speaker"])'))

    def test_non_evidence_24(self):
        self.assertFalse(evidence('s.verify_files'))

    def test_non_evidence_25(self):
        self.assertFalse(evidence('def verify_files(): pass\ns.verify_files(a,b)'))

    def test_non_evidence_26(self):
        self.assertFalse(evidence('def verify_batch(): pass\ns.verify_batch(a,b)'))

    def test_non_evidence_27(self):
        self.assertFalse(evidence('class C:\n def VoiceEncoder(self): pass\nVoiceEncoder(); e.embed_utterance(a)'))

    def test_non_evidence_28(self):
        self.assertFalse(evidence('def embed_utterance(): pass\nVoiceEncoder(); e.embed_utterance(a)'))

    def test_non_evidence_29(self):
        self.assertFalse(evidence('def from_pretrained(): pass\np.from_pretrained("speaker-verification")'))

    def test_non_evidence_30(self):
        self.assertFalse(evidence('def verify_speaker(): pass\ns.verify_speaker(a)'))

    def test_non_evidence_31(self):
        self.assertFalse(evidence('def identify_speaker(): pass\ns.identify_speaker(a)'))

    def test_non_evidence_32(self):
        self.assertFalse(evidence('broken syntax !'))

    def test_claim_00(self):
        self.assertEqual(claims('```\nspeaker verification\n```'), (False, False))

    def test_claim_01(self):
        self.assertEqual(claims('   ~~~~text\nspeaker verification\n   ~~~~'), (False, False))

    def test_claim_02(self):
        self.assertEqual(claims('`speaker verification`'), (True, False))

    def test_claim_03(self):
        self.assertEqual(claims("doesn't verify speaker identity"), (False, True))

    def test_claim_04(self):
        self.assertEqual(claims('no speaker verification'), (False, True))

    def test_claim_05(self):
        self.assertEqual(claims('speaker-verification'), (True, False))

    def test_claim_06(self):
        self.assertEqual(claims('speaker verifications'), (False, False))

    def test_exclusion_00(self):
        self.put("README.md", "speaker verification")
        self.put('fixtures/a.py', "s.verify_files(a,b)")
        result = audit(self.root)
        self.assertFalse(result["production_evidence"])
        self.assertEqual(result["test_evidence"], False)

    def test_exclusion_01(self):
        self.put("README.md", "speaker verification")
        self.put('docs/a.py', "s.verify_files(a,b)")
        result = audit(self.root)
        self.assertFalse(result["production_evidence"])
        self.assertEqual(result["test_evidence"], False)

    def test_exclusion_02(self):
        self.put("README.md", "speaker verification")
        self.put('examples/a.py', "s.verify_files(a,b)")
        result = audit(self.root)
        self.assertFalse(result["production_evidence"])
        self.assertEqual(result["test_evidence"], False)

    def test_exclusion_03(self):
        self.put("README.md", "speaker verification")
        self.put('test_app.py', "s.verify_files(a,b)")
        result = audit(self.root)
        self.assertFalse(result["production_evidence"])
        self.assertEqual(result["test_evidence"], True)

    def test_exclusion_04(self):
        self.put("README.md", "speaker verification")
        self.put('app_test.py', "s.verify_files(a,b)")
        result = audit(self.root)
        self.assertFalse(result["production_evidence"])
        self.assertEqual(result["test_evidence"], True)
