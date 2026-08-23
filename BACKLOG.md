# Backlog — Explee test task

Durable tracker for work that is accepted but not yet started. Open items here are
not "someday": each carries the next concrete action.

## Open

### Task 2 — STT engine comparison (NOT STARTED)
Compare ≥5 speech-to-text engines on ~1 hour of Russian speech with dense English IT
terminology, and design the evaluation itself.

Next action: assemble the audio corpus (a conference talk + a podcast + one
phone-quality segment, so acoustic conditions vary) and freeze the glossary of terms
whose loss actually costs meaning.

Design already decided, to avoid re-deriving it:
- Primary metric is **term-level recall over a domain glossary**, not WER. Russian
  morphology penalises "RAG" vs "RAGа" while the cost of errors is wildly uneven — a
  lost filler word costs nothing, "РАКа" for RAG costs the sentence.
- WER/CER stay as background, with normalisation (case, punctuation, е/ё, numerals).
- Second axis, probably the most valuable finding: the same engine **with and without
  a domain glossary** (Deepgram keyterm, AssemblyAI word_boost, Whisper initial_prompt,
  Speechmatics custom dictionary). The practical answer to their pain may be "add a
  glossary", not "switch vendor".
- Include Russian-specific engines the field usually forgets (Yandex SpeechKit, GigaAM,
  Salute) and LLM-based transcription, which tends to win on code-switching because it
  knows ClickHouse is a product.
- Ground truth by consensus: run every engine, hand-adjudicate only where they diverge,
  plus an exhaustive manual pass over the glossary terms. Blind to which engine produced
  which candidate.

### Task 3 — harness artifact (NOT STARTED)
Ship one file plus 2–3 lines on where it lives and what it does.

Next action: choose between two candidates and write the note.
- `live-tree-guard.py` — carries a real incident, a 1969-edit measurement taken before
  enabling it, and a deliberate opt-in scope decision.
- the `learn-from-corrections` loop — carries a held-out evaluation that rejected the
  obvious approach on evidence (keyword detector F1 0.42 vs LLM 0.97).
Their brief says taste and maturity matter more than size, so the tiebreak is whichever
shows a decision being made on measurement rather than instinct.

## Closed

_(nothing yet)_
