# Uploading your own quiz

This page is for tank owners (usually a teacher) who want their own
multiple-choice questions in the game. One tank uses **either** the built-in
questions **or** one of your uploaded quizzes — not both at once.

Your upload is private to your account. Only tanks you own can use it.

## Formats

You can upload any one of these:

| Format | Best for | Template |
| --- | --- | --- |
| `.csv` | Excel exports, Google Sheets | `/quizzes/template/csv/` |
| `.xlsx` | Excel workbooks (first sheet only) | `/quizzes/template/xlsx/` |
| `.txt` | Text editors, Notepad | `/quizzes/template/txt/` |
| `.docx` | Word documents (paragraphs only) | `/quizzes/template/docx/` |

PDF is **not** supported. PDF layouts and scans cannot be read reliably, and a
wrong answer key would silently break the game.

Each template already contains three sample items in the correct layout. Start
from the template, keep the header/first lines, and replace the samples.

## CSV and Excel layout

The first row must be a header:

```
no,question,a,b,c,d,answer,explanation
1,What is 2 + 2?,3,4,5,6,B,Add the two numbers.
2,Which planet do we live on?,Mars,Earth,Venus,,B,
```

- `no`, `d` and `explanation` are optional.
- `answer` is a letter (`A`-`D`) or a number (`1`-`4`).
- Use 3 or 4 choices. Leave `d` empty for a 3-choice question.
- CSV files may use commas, semicolons or tabs; UTF-8 and Windows-1252 are both
  accepted. The preview tells you which encoding was used.

## Text and Word layout

```
1. What is 2 + 2?
A. 3
B. 4
C. 5
D. 6
Answer: B
Explanation: Add the two numbers.

2. Which planet do we live on?
A. Mars
B. Earth
C. Venus
Answer: B
```

- An item ends at its `Answer:` line.
- Question numbers are optional; without them, items are numbered in order.
- Choices must be **typed** as `A.`, `A)` or `(A)`, in order, starting at A.
- A question may span several lines.
- `Explanation:` is optional and follows the answer.

**Word's automatic lists do not put their numbers or letters in the file.** If
you use one, the uploader cannot see the choice markers and reports:
"Choices must be typed as A. B. C. D. (Word automatic lists can't be read)."
Turn the automatic list off and type the letters yourself, or use CSV/Excel.

## How difficulty bands work

Bands map **item numbers** (the `no` column, or the `1.` prefixes) to Easy,
Medium or Hard. Items outside every band are never used.

Example: "items 1-20 = Easy, items 25-40 = Medium":

| Difficulty | From item | To item |
| --- | --- | --- |
| Easy | 1 | 20 |
| Medium | 25 | 40 |
| Hard | (empty) | (empty) |

Items 21-24 and 41+ are not used. Numbers are never renumbered, so the ranges
mean exactly what you see in your file even if some items were skipped for
errors.

After uploading you see a preview with suggested bands (three roughly equal
thirds), errors and warnings. Adjust the numbers, save the bands, then press
**Activate quiz**. A quiz needs at least 10 usable banded questions.

A band with fewer than 5 questions is allowed but warned about, because players
will see repeats sooner.

## Choosing how questions are picked

In the tank settings, under **Quiz source**:

- **By fish stage** (default): a new fish gets Easy; after it evolves it gets
  Medium, then Hard. If a band is missing, the nearest band is used, preferring
  easier questions.
- **Fixed band**: always Easy, Medium or Hard, whichever you pick.
- **All bands**: random across every band.

Choices are shuffled on the server for every question, and the question pool is
cycled so players do not see the same item twice until they have seen them all.

## Common errors and fixes

| Message | Fix |
| --- | --- |
| "The first row must be a header..." | Keep the header row, or download the template. |
| "the answer is missing or not a letter" | Put `Answer: B` (or an `answer` column with `B`/`2`). |
| "no choices were found" | Type `A.`, `B.`, `C.` in the text; avoid Word auto-lists. |
| "two choices are the same" | Make every choice different (case does not matter). |
| "this item number is used twice" | Give each item its own `no`. |
| "the question is too long" | Keep questions under 300 characters, choices under 100. |
| "Unsupported file type" | Only `.csv`, `.xlsx`, `.txt` and `.docx`; `.xlsm` macros are refused. |
| "That document looks like a compressed archive bomb" | Re-save the file; the uploader rejected an abnormally compressed archive. |

Bad items are skipped; the rest still import. The preview lists each problem
with its row or line number, and you can fix the file and upload again.

## Editing and deleting

- **Disable** a question in the preview to stop using it without re-uploading.
  Re-enable it the same way.
- **Rename** the quiz at any time.
- **Delete** the quiz when you no longer need it. Tanks using it revert to the
  built-in questions automatically; past answers keep working because every
  attempt stores its own snapshot.

## What is stored

Only the parsed questions, their bands, and the answers are stored. The
uploaded file itself is discarded after parsing and is never written to disk,
the database, or the logs.

Do not include students' personal information in questions. Only upload
content you have the right to use.
