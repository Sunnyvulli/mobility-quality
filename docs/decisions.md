# Decisions

## SQLite and loopback for an inspectable reference
A dependency-free pipeline and small read-only API let reviewers run the core without credentials. SQLite supplies atomic snapshot/audit replacement; it is not evidence of distributed operations or multi-user authentication. Whole-file loading and comparison are intentionally bounded to the included historical source.

## Capture source bytes once; verify actual replay contents
Hash and parse one captured byte sequence. Under BEGIN IMMEDIATE, compare every typed stored observation against the validated source before using cached audit metadata. This repairs altered, missing or added observations and blocks cooperating concurrent writers during verification/replacement. Tests inject failure and confirm rows, manifest and active hash roll back together, then retry. Schema/audit metadata and the filesystem operator are trusted; hashes do not make storage tamper-proof. [SQLite transaction control](https://www.sqlite.org/lang_transaction.html).

## Whole-day past-only evaluation and honest information availability
Use three expanding-history windows and three seeds with a calendar-only forest, training mean and online weekly-lag baselines. Seven-day-old observations are available as each test hour arrives; this is not one fixed 28-day forecast. Earlier shuffled/leaky/weather-assisted studies remain labeled as retrospective/negative controls. Paired daily bootstrap uncertainty is exploratory and does not model all training or temporal dependence uncertainty. [Full protocol](https://github.com/Sunnyvulli/Sunnyvulli.github.io/blob/main/research/temporal-followup.md).

## Independent repository without altering prior history
Import a byte-identified source snapshot and retain its original portfolio history/provenance links. Adapt root-only paths for Make, Compose and CI. Keep old portfolio URLs available instead of deleting files before downstream links migrate. Independent CI reruns the actual core, study and container; inherited portfolio status alone does not satisfy the standalone check. Future code changes should be made here first and any compatibility copy synchronized explicitly rather than silently diverging.
