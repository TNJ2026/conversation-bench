# Desktop Conversation Experience Benchmark v2

[English](README.md) | [中文](README.zh-CN.md)

A human-operated benchmark for comparing multi-turn conversations in DeepSeek Harness (`dsh`), ChatGPT (`chatgpt`), and Hermes (`hermes`). Requires Python 3.9 or later and uses only the standard library. The entry point is `study.py`.

The suite contains 18 cases across six categories, with three project scenarios per category. The default two-app plan contains 36 conversations; a single-app plan contains 18, and a three-app plan contains 54. It provides prompts one turn at a time, separate material workspaces, artifact snapshots, protocol-aware comparison groups, reports, and anonymized text-review exports.

For the short-conversation suite, an operator sends prompts to the actual desktop application and records the results. The short-conversation tool does not click application controls, call model APIs, or simulate a user by answering its own questions. A separate automatic long-context runner drives the native DSH SDK profile, as described below. The supplied case prompts and command-line messages are currently in Chinese; this English README does not translate the benchmark itself.

## Select applications

Use `--products` when creating a plan. Provide a comma-separated list; the default remains `dsh,chatgpt`. Existing plans and records do not need to be changed.

```sh
# Hermes only: 18 conversations
python3 study.py create --products hermes --output studies/hermes-desktop-1/plan.json
python3 study.py next --plan studies/hermes-desktop-1/plan.json
# DSH and Hermes: 36 conversations
python3 study.py create --products dsh,hermes --output studies/dsh-hermes/plan.json
# All three applications: 54 conversations
python3 study.py create --products dsh,chatgpt,hermes --output studies/three-apps/plan.json
```

If a plan already exists, run `next` instead of repeating `create`. The tool refuses to overwrite an existing plan. All applications use the same `begin`, `submit`, `finish`, and `report` workflow below.

Start a separate conversation for each case, associate it only with its assigned material workspace, and send only the current turn. Record the actual model, reasoning effort, permissions, plugins, and memory settings. Keep future prompts, acceptance criteria, and other applications' answers away from the target conversation. For interruption cases, verify that the intervention reaches the running task; a queued message does not establish an immediate interruption.

Product labels identify the application under test, not the model. If you actually use Codex or another client, record that explicitly. A product label does not establish that clients or models were matched.

## Get started

Historical records, process evidence, and comparison reports are kept in a local archive outside this project and are not uploaded with the source. The archive's path mapping and checksum manifest support tracing the original evidence.

Create a new plan, then inspect its next job:

```sh
git clone https://github.com/TNJ2026/conversation-bench.git
cd conversation-bench
python3 study.py create --output studies/new-round/plan.json
python3 study.py next --plan studies/new-round/plan.json
```

The output identifies the application, case, and job to run next. Begin that job using its actual ID and configuration. `J001` below is only an example:

```sh
python3 study.py begin --plan studies/new-round/plan.json --job J001 \
  --model 'actual model and reasoning effort' --app-version 'actual app version' \
  --permissions 'actual permissions' --plugins 'actual plugins' --memory 'actual memory settings' \
  --method desktop --isolated --unexposed
```

`--isolated` declares that you used a separate new conversation. `--unexposed` declares that the target has not seen future prompts, acceptance criteria, or another application's answers. Supply these flags only when those conditions are actually met. The default method is `selftest`, so self-generated answers are not mistaken for formal desktop evaluations. Self-tests can be recorded but are excluded from formal comparison groups and anonymized reviews.

**Keep the test operator separate from the AI under test.** You or an independent operator should control the terminal. Do not give the target this README, the scripts, or the complete case, and do not ask it to manufacture its own test records. Each target conversation receives only the current prompt and its assigned workspace. Showing one prompt at a time does not prevent an AI with full filesystem access from reading the case files; the operator must enforce access isolation.

## Record a turn

1. `begin` prints the record path, assigned workspace, and first prompt. Bind the target application to that workspace or give it the absolute workspace path. Workspaces are created in the sibling `conversation-bench-workspaces/` directory and contain task materials, without the cases or scoring criteria.
2. Send the current prompt to the target application and observe its actual behavior. Use a stopwatch or screen recording when measuring feedback, completion, and operator time.
3. Save the complete answer text to a UTF-8 file, such as `/tmp/bench-answer.txt`. Store tool activity, additional follow-ups, screenshot paths, and anomalies separately in `/tmp/bench-notes.txt`. Keep tool logs out of the answer text used for character checks.
4. Submit the turn. The tool then displays the next prompt:

```sh
python3 study.py submit \
  --record studies/new-round/records/J001.json \
  --answer /tmp/bench-answer.txt --notes /tmp/bench-notes.txt \
  --elapsed 48 --first-feedback 3 --active-seconds 12 \
  --corrections 0 --actions 2
```

These numbers are examples; replace them with observations. Omit unmeasured metrics rather than entering zero. Times are in seconds: `elapsed` runs from sending the prompt to the end of the turn, `first-feedback` measures the first informative response, and `active-seconds` measures the human operator's active time. `corrections` excludes the case's planned follow-up prompts.

A second `submit` writes the next turn of the same record. Check the displayed turn number and do not submit the same answer twice. To resume after a pause, run `next --plan ...` to display the current unsubmitted turn. Each submission is saved atomically; already submitted turns are not rerun or overwritten.

## Interruption cases

The first step of an interruption case gives the operator both a task prompt and an intervention. Send them in the actual application while the original task is still running. Send the intervention before the first write or within five seconds of starting, whichever comes first. If the task has already finished, the interruption trial is invalid.

Save both responses, in order, in the first turn's answer file. In the notes, record when the intervention was sent, when the application acknowledged it, and when subsequent tool calls or writes occurred. Distinguish an in-flight write finishing from a new write initiated after the intervention.

```sh
python3 study.py submit --record studies/new-round/records/J001.json \
  --answer /tmp/bench-answer.txt --notes /tmp/bench-notes.txt \
  --interruption-observed --interrupt-delay 1.5
```

Supply `--interruption-observed` only when you actually observed an intervention during the running task, and only on the turn that has a planned intervention. Record the delay only when measured. Without that observation, or when the recorded delay exceeds the five-second limit, the tool refuses to mark an interruption case as valid: the operator protocol was not met, so set `valid` to `false` and give the reason. Intervention timing is a protocol check, listed separately in the report and not counted among the application's automatic checks.

## Finish and score a conversation

After recording all turns, generate a scoring template:

```sh
python3 study.py finish --record studies/new-round/records/J001.json
```

Edit the generated `J001-scores.json`:

- `valid`: set to `true` when the conversation was run turn by turn with the correct materials and no future-prompt leakage. Set to `false` for a protocol violation and explain it in `invalid_reason`. Poor performance or a failed task does not by itself invalidate the test.
- `acceptance[].pass`: `true`, `false`, or `null` for an unassessed item. A valid conversation that ran every turn must have every item assessed; only one that failed early (`--outcome failed`) may leave `null`. In a valid conversation every item needs at least six non-whitespace characters of `evidence`: the turn, quotation, file, or specific behavior for an assessed item, and the reason it could not be judged for an unassessed one.
- `clarity` looks only at what the application said: whether its replies make clear what it did, on what basis, and what remains undone or uncertain. `cooperation` looks only at what it did: whether it stayed within the scope and pace of the instructions, and how much correction it needed beyond the case's planned follow-ups. Each has its own level-by-level standard in the scoring template's `rubric` (written in Chinese). Use an integer from 1 to 5, or `null`; a scored item needs specific events in `clarity_evidence` or `cooperation_evidence`. Both come from an operator who knows which application is being scored. They are not blind ratings, and the report labels them accordingly.

When a human pass contradicts a linked automatic check (for example, "sections one and three kept verbatim" is passed although the automatic check found the overview changed), `finish` lists the conflicts and refuses to close the record. Change the verdict, or, if the automatic check does not apply here, explain why in `evidence` and close with `--confirm-conflicts`; the conflict still appears in the report. Only some acceptance items have a matching automatic check; the rest rely entirely on human judgment.

```sh
python3 study.py finish --record studies/new-round/records/J001.json \
  --scores studies/new-round/records/J001-scores.json
python3 study.py next --plan studies/new-round/plan.json
```

If a task fails and cannot continue, close it early with failure evidence:

```sh
python3 study.py finish --record studies/new-round/records/J001.json \
  --scores studies/new-round/records/J001-scores.json --outcome failed
```

Valid failures remain in comparisons; invalid trials are listed separately. Closed records cannot be overwritten. Create a new plan for a retest.

## Reports and anonymized review

```sh
python3 study.py report --plan studies/new-round/plan.json
open studies/new-round/report.html
python3 study.py blind --plan studies/new-round/plan.json
```

`open` is a macOS command; on other systems, open the HTML file in a browser.

Reports separate valid formal trials from self-tests, invalid trials, and records awaiting confirmation. A complete comparison group requires the same plan, case snapshot, repeat number, and mode, with **all selected applications closed as valid trials**. In a three-app plan, two completed applications do not form a complete three-app group. Valid failed conversations can still be included. Single-app plans record results without cross-app comparisons or anonymized comparative exports. For older V2 plans without a saved application list, the tool derives participants from the jobs without rewriting the plan.

Model names and configuration remain visible in reports. A `controlled` label does not prove that the actual models match. Per-turn timing, operator effort, checks, and artifact snapshots appear in the evidence details. Multiple constraint checks are not independent samples, and the tool does not produce an overall ranking.

How to read the summary table:

- Submitted turns: turns submitted out of the case's total. Automatic checks cover submitted turns only, so a conversation that failed early has fewer checks, and its counts cannot be compared directly with a conversation that ran to the end.
- Automatic checks: passed, failed, and awaiting manual review are counted separately and not combined into a ratio.
- Protocol checks: whether the operator sent the intervention in time. They do not count for or against the application.
- Human acceptance: passed, failed, and unassessed counts, with the total number of items.
- Conflicts: places where a human pass contradicts a linked automatic check. Older case snapshots carry no links and show as not reconciled.
- Clarity and cooperation: the operator's non-blind ratings.

Anonymized exports contain prompts, answers, randomized labels, and a scoring template. Two-app groups use A/B; three-app groups use A/B/C. Product labels and configuration are removed, while the identity mapping is saved separately in a `KEY-DO-NOT-SHARE` file under the plan directory. Never give that mapping to reviewers. Answers may themselves reveal product names or paths, so inspect exports before sharing; complete anonymity is not guaranteed.

Text reviews use three 1–5 dimensions: factual accuracy, instruction following, and usefulness. The standard for each level is in the `rubric` of the exported `scores.json` (written in Chinese). When the reviewer returns it, put `scores.json` back in its export directory and run `report` again: the report gains an anonymized text review section that restores each application from the identity mapping and lists the scores with their evidence. A value outside 1–5 is shown as invalid and missing evidence is shown as missing; no averages are computed. The merged report reveals application identities, so do not send it back to reviewers. Score desktop interaction separately rather than inferring it from answer text.

## Additional plans and retests

```sh
python3 study.py list
# All 18 cases, once per default application: 36 conversations
python3 study.py create --output studies/another-round/plan.json --seed 73
# Retest two cases, twice per default application
python3 study.py create --cases revision-knowledge,context-training \
  --repeat 2 --output studies/focused-retest/plan.json
# Hermes only, two cases repeated twice: 4 conversations
python3 study.py create --products hermes --cases revision-knowledge,context-training \
  --repeat 2 --output studies/hermes-retest/plan.json
```

Plans freeze their case snapshots and randomize case order. Two-app plans retain the alternating order; three-app plans rotate application order. `--seed` makes the ordering reproducible. Selected applications and their order are saved in the plan; duplicate and unknown applications are rejected. The default mode records everyday settings. Use `--mode controlled` after manually matching configuration. Each job gets its own material copy and workspace; an existing workspace is not reused.

## Checks and limitations

Text checks cover required strings, required dates, minimum and maximum non-whitespace character counts, paragraph count, the absence of Markdown heading lines, a fixed paragraph, and verbatim preservation of paragraphs identified by blank lines. Counts include punctuation and Markdown. Dates written as `2026-12-15`, `2026/12/15`, or `2026年12月15日` are treated as the same date; a date without its year is marked for manual review instead of pass or fail. A complete date with an incorrect year is not treated as a yearless date. Paragraph checks expect the answer file to contain only the deliverable, since an introductory line counts as a paragraph. A check the tool cannot run is reported as needing review, never silently skipped. The short-text revision cases require 450–550 characters before shortening to 220; the final turn does not restate the key constraints. An initial draft that is too short fails the initial requirement; a later answer below 220 characters does not by itself demonstrate successful shortening.

Artifact-review cases save HTML, Markdown, CSV, and source-material snapshots after each turn. They check the source file's hash, that the first report contains all three required sections and references no external scripts, styles, or media, that the two untouched sections stay verbatim, and that the risk section actually changed in each revision turn. Discussion-only and read-only turns compare file hashes with the previous turn. Missing-material cases mark newly appearing paths for human review. A new template or simulated data file does not by itself prove that the agent fabricated reading the missing source; judge that from the answer and tool evidence. Interruption cases compare the recorded delay with the five-second limit as a separate protocol check; a conversation over the limit cannot be marked valid, and the timing is left for manual review when no delay was measured. Files that are not UTF-8 are still recorded and flagged for review. A changed section is not proof of a correct change. Hashes cannot detect a file being changed and then restored, or establish that a browser preview rendered correctly. Preview behavior, tool activity, and live interruption still require operator evidence. Files and screenshots may contain personal information; inspect them before sharing.

The short-conversation catalog is `cases-v2.json`. Running `suite.py` regenerates the built-in V2 cases and overwrites manual edits to that file. `checks.py` provides the text-constraint checks.

## Long-context compaction comparison

The separate [long-context compaction case](docs/long-context-compaction-qinglu.md) uses branches from a shared checkpoint, evidence of actual context compaction, and two probe stages: closed-book recall and read-only retrieval. Complete prompts and a record template are in [the case JSON](cases/long-context-compaction-qinglu.json). Its instructions and prompts are currently in Chinese.

The automatic entry point is `python3 study.py long`. It uses the native DSH `sdk` profile, not the desktop UI, and remains separate from the 18 short-conversation cases. It sends real prompts through DSH, closes the runtime before cloning its isolated test home, runs native `/compact`, and requires durable history-replacement evidence covering all three seed turns. It never treats an assistant-written summary as proof of compaction.

Install a DSH CLI that supports `session/query`, `session/resume`, and native `/compact`, and configure provider credentials in the launch environment. The runner does not copy credentials or plugins from your daily desktop profile. Python still needs no third-party packages.

```sh
python3 study.py long create --model deepseek-v4-flash --effort low \
  --load-batches 12 --output studies/long-1/run.json
python3 study.py long run --record studies/long-1/run.json
python3 study.py long grade --record studies/long-1/run.json
# Fill in protocol reviews and per-anchor grades in scores.json, then validate:
python3 study.py long grade --record studies/long-1/run.json \
  --scores studies/long-1/scores.json
python3 study.py long report --record studies/long-1/run.json
```

Use `run --max-actions N` to pause at a safe action boundary and run the same command to continue. Before checkpointing, `extend --record ... --batches N` appends new, uniquely numbered batches. Automatic compaction in the control, tools used during closed-book recall, or insufficient replacement evidence invalidate the trial. After a timeout or disconnection, the outcome is uncertain and the runner refuses an automatic resend. See the [execution and recovery guide](docs/long-context-runner.md) (Chinese). These commands invoke the actual target model; protocol-fixture tests alone are not benchmark measurements.

Omitted answers are recorded separately as instruction omissions and graded unknown, not wrong; an explicitly incorrect answer is wrong. Each anchor in that case is graded by hand as correct, partial, unknown, or wrong; the points a correct answer needs are listed under `required_points` in the JSON. A retention score (1 for correct, 0.5 for partial) is reported next to the number of wrong items, and the two are never merged into one figure. A second uncompacted branch estimates variation unrelated to compaction; a difference between the compacted branch and the control that is no larger than this variation is not attributed to compaction. Semantic grading remains manual. The runner validates grade completeness, exact-text passes, omission categories, source requirements for claimed retrieval, and the run/answer snapshot associated with the score sheet. Select the final conclusion as an exact span of each recovery answer to check its length, dates, current budget, and fixed sentence; unidentified spans remain unassessed. Access isolation, external writes and memory updates require explicit human protocol review; filesystem snapshots alone cannot prove their absence.

`longcase.py` regenerates the synthetic load in that JSON and leaves the hand-written turns, probes, and scoring untouched. If twelve batches are not enough to reach compaction, `python3 longcase.py --extra N` prints N further batches with new ticket numbers without rewriting the case file.


For detail-recall experiments, use `--case cases/long-context-compaction-qinglu-v7.json --load-batches 12`. V7 queries unique keyed receipts rather than periodic topic labels. All queried source tickets must be supplied, and the runner enforces the case's three allowed grades. Legacy V6 is retained for historical reference but cannot start or continue a new trial because its answers can be inferred from later batches. See the [updated protocol](docs/long-context-runner.md).

## Task completion after compaction (v8)

[V8 / V8.1 protocol and commands](docs/task-success-v8.md) adds a project handoff task using the existing isolated A/A_repeat/B runner. It checks current decisions, evidence, and actionable next steps. All ten acceptance conditions must pass for full delivery success; passing nine is still incomplete. Closed-book delivery and assisted recovery are reported separately. Protocol-invalid runs have no valid success rate. V7 remains a separate exact-recall benchmark. Original V8 results are exploratory due to an ambiguous receipt instruction. Use the frozen V8.1 case for new baselines: it clarifies the placeholder and accepts common emphasis, bracket, and label presentation while requiring the correct ticket/receipt pair on the same line. Old cases and scoring rules remain unchanged. V8.1 has local baseline records with a separate non-blind AI review and unresolved items. The opt-in [current-session history plugin](docs/current-history-plugin.md) is implemented and has passed a real DSH Web integration smoke test; three-run V7 and V8.1 comparisons are now complete. See the [0.1.0 results and limitations](docs/current-history-plugin-results-0.1.0.md).

## Transfer materials and interleaved comparison (v9)

[V9](docs/transfer-v9.md) adds three frozen maintenance-handoff materials with new identifiers, constraints, receipts, multiline fields, same-line neighbors, superseded versions, and repeated hits. It scores ten exact receipts plus three handoff conditions. `transfercase.py prepare` creates six paired, interleaved 0.1.0/0.1.1 plans without calling a model; `transfercase.py run` executes that frozen schedule explicitly. Inputs, plugin files, and runner sources are checked before execution. See the [archived 0.1.1 results](docs/current-history-plugin-results-0.1.1.md) and [complete test workflow](docs/plugin-test-workflow.md).

## Run the project checks

```sh
python3 -m unittest -v
```

Tests use temporary data and do not manufacture product-evaluation results. They cover every text check, case counts and agreement between the saved catalogs and their generators, application selection and ordering, protocol exclusions, retention of valid failures, section and file-change checks, missing-material and interruption handling, per-turn recording, resuming, score validation (unassessed items, evidence length, empty values), conflicts between human acceptance and automatic checks, late interventions being refused as valid, the report's summary columns, command-line defaults, HTML escaping, two- and three-app anonymized exports and merging returned review scores into the report, compatibility with older V2 plans, and the long-context load's numbering, variety, freedom from anchor wording, and complete grading points.
