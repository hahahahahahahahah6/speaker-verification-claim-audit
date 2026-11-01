# Audio identity claim audit

An offline static audit tool that compares documentation promises with Python source fingerprints. It parses source without executing it. It does not determine anyone's identity from audio.

## Install and run

Requires Python 3.9 or later. No runtime dependencies are required.

```sh
python3 -m pip install .
speaker-verification-claim-audit /path/to/project
python3 -m speaker_verification_claim_audit /path/to/project --json
python3 -m speaker_verification_claim_audit --version
```

The root README and Markdown files beneath any docs directory are scanned by paragraph. Fenced blocks are excluded; inline code counts. Matching folds case, expands negative contractions, replaces hyphens with spaces, and collapses whitespace. Negative spans are removed before positive matching.

Source evidence comes from AST call patterns in a single module. Local function and method definitions shadow imported names. Syntax errors provide no evidence. Symlinks are excluded. Fixtures, examples, and docs are excluded from source evidence; test evidence is reported separately.

Recognized call patterns:

```text
.verify_files(...) / .verify_batch(...)
VoiceEncoder(...) together with .embed_utterance(...) in one module
.from_pretrained("speaker-verification")
.verify_speaker(...) / .identify_speaker(...)
```

Imports, strings, transcription, segmentation, audio input or output, isolated embeddings, and similarity calculations alone do not supply evidence. This is a static heuristic: matching calls do not prove runtime correctness, model quality, or accuracy.

## Results

The JSON result contains verdict, findings, document and source paths, and evidence flags. Each finding includes an id, severity, and message. A verdict reports any discrepancy even when it falls below the configured failure threshold.

```text
documented-speaker-verification-claim-false: HIGH, or MEDIUM for test-only evidence
documented-no-speaker-verification-claim-false: HIGH
```

Exit status is 0 for no findings at the failure threshold, 2 for findings at or above it, and 1 for usage or I/O errors. The default threshold is HIGH.

```sh
python3 -m speaker_verification_claim_audit . --verbose
python3 -m speaker_verification_claim_audit . --ignore vendor --ignore build --fail-on MEDIUM
python3 -m unittest discover
python3 -m build
```

Ignored paths are root-relative prefixes with directory boundaries. The tool uses no network and writes no files. Licensed under MIT.
