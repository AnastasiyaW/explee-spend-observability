# Backlog — Explee test task

Durable tracker for work that is accepted but not yet started. Open items here are
not "someday": each carries the next concrete action.

## Open

### Task 2 — STT engine comparison (IN PROGRESS)
Compare ≥5 speech-to-text engines on ~1 hour of Russian speech with dense English IT
terminology, and design the evaluation itself.

Next action: deploy the frozen four-segment corpus and reviewed v2 runner to the
dedicated 24 GB CUDA host, complete the 28-artifact matrix, human-adjudicate bounded term
intervals, then generate and publish `docs/stt.html`.

Design already decided, to avoid re-deriving it:
- Primary metric is **term-level recall over a domain glossary**, not WER. Russian
  morphology penalises "RAG" vs "RAGа" while the cost of errors is wildly uneven — a
  lost filler word costs nothing, "РАКа" for RAG costs the sentence.
- WER/CER stay as background, with normalisation (case, punctuation, е/ё, numerals).
- Seven variants cover five independent engine families: three faster-whisper sizes
  (so one best Whisper is chosen), plus GigaAM, Qwen3-ASR, Meta MMS and Vosk.
- Ground truth is not model consensus: systems only discover bounded candidates; a
  human listens and confirms each scoring slot against the frozen audio hash.
- The public report must show the overall ranking, the within-Whisper decision, why
  each experiment was included, and why the winner beat the alternatives.

## Closed

### Task 3 — harness artifact

Selected [`task3-distill-feedback.md`](task3-distill-feedback.md): a submission copy of the actual skill plus the
required three-line location/purpose note. It won the tiebreak because the held-out evaluation
rejected the obvious keyword detector (F1 0.42 versus 0.97), and its durable-rule writes remain
human-gated.
