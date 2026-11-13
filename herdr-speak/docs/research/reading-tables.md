# Reading markdown tables aloud

Research notes, November 2026. The question: how should Speak turn a markdown table in an agent reply into speech that a developer can follow without looking at the screen? The notes cover screen readers, W3C guidance, read-aloud products, voice-UI style guides, and published research. They end with what Speak's own Kokoro pipeline does with the relevant punctuation and symbols, measured locally.

Nothing here has been implemented. The thresholds below are starting values derived from the cited guidance. No source tests them on tables spoken by a TTS engine, so they need tuning by ear.

## Summary of recommendations

**What Speak does today.** [`clean_for_speech`](../../herdr_speak/text.py) replaces every run of lines that *start with* `|` with one localized line, "Table skipped." ([`catalog.py`](../../herdr_speak/catalog.py)), the same treatment fenced code gets ("Code block skipped."). Two gaps:

- A GFM table without leading pipes (`Name | Status` / `--- | ---`) is valid ([GFM spec](https://github.github.com/gfm/#tables-extension-)) but isn't detected. It is read as run-on prose, and Misaki silently drops the pipes and the delimiter row. Measured: `Name | Status.` becomes "Name Status", and `Paris | ✅ ok.` becomes "Paris okay".
- The skip note doesn't say how much was skipped.

**Reading modes** (one setting, for example `tables = "auto"`):

| Mode | What is spoken | When it fits |
|---|---|---|
| `skip` | "Table with 12 rows, skipped." | Listener never wants table content (today's behavior, plus the size) |
| `summary` | The announcement only: size and column names | Big tables; listener will look at the screen if interested |
| `rows` | The announcement, then every row with each value prefixed by its column header | Listener wants everything regardless of size |
| **`auto` (default)** | `rows` for small tables. For large ones, the announcement, the first 3 rows, then "and N more rows." | Most agent replies |

`auto` should be the default. Tables in agent replies are usually short status, comparison, or change lists, and they carry the answer, so skipping them loses content (code blocks differ: code doesn't survive speech). Large tables follow the voice-UI rule of not reading long lists in full ([Google](https://developers.google.com/assistant/conversation-design/scale-your-design), [Alexa](https://developer.amazon.com/en-US/alexa/alexa-haus/patterns-and-components/patterns-lists)).

**Announcement before the table**, as its own paragraph: `Table, 5 rows. Columns: File, Change, Tests.`

- Give the size first. Screen readers announce dimensions on entry ([NVDA source](https://github.com/nvaccess/nvda/blob/af55fb6b6485f08757733aa7cd1d6f30e8a19563/source/speech/speech.py), [TalkBack strings](https://github.com/google/talkback/blob/229212fdf5842191d0a93fc95d9ca1423b346866/talkback/src/main/res/values/strings_compositor.xml)), and Alexa's list checklist asks for a preamble with the item count.
- Count data rows only, without the header row.
- List the column names only when there are 5 or fewer. Otherwise say "9 columns, starting with Name, Status, Owner."

**Row format.** Make each row its own paragraph, the first cell as its label, then `Header: value` pairs separated by semicolons, ending with a period:

> auth.py: Change: added token refresh; Tests: yes.

This is the rendering the HTML 4 spec gives as its speech example ([HTML 4.01 §11.4](https://www.w3.org/TR/html401/struct/tables.html#h-11.4)), with the compact "row header first" variant. It is also the "guided" reading that scored best for listeners in [Spiliotopoulos et al. 2005](https://dspiliot.github.io/publications/Spiliotopoulos%20et%20al.%20-%202005%20-%20Experimentation%20on%20Spoken%20Format%20of%20Tables%20in%20Auditory%20User%20Interfaces.pdf).

- If the first column is numeric or empty, don't use it as the label. Prefix it like any other column.
- After a fully read table, add "End of table." (NVDA says "out of table") when prose follows.

**Thresholds for `auto`** (all configurable):

- Read in full when there are **≤ 6 data rows and ≤ 5 columns**.
- Otherwise read **3 rows**, then "and N more rows."
- Over **8 columns**, give the announcement only.

Why these numbers:

- Spoken lists are capped at about 5 to 6 items in voice-UI guidance ([Alexa](https://developer.amazon.com/en-US/alexa/alexa-haus/patterns-and-components/patterns-lists), [Google](https://developers.google.com/assistant/conversation-design/scale-your-design)).
- Short-term memory holds about 4 chunks ([Cowan 2001](https://memory.psych.missouri.edu/assets/doc/articles/2001/cowan-bbs-2001.pdf)), which suggests one label plus up to 4 header–value pairs per row.
- Speak assumes 14 characters per second ([`daemon.py`](../../herdr_speak/daemon.py)), so a 4-column row with header prefixes takes about 5 to 7 seconds, plus a 1.4 s gap. Six such rows take about 45 seconds.

**Cell handling:**

- **Empty cells, and cells holding only `-`, `–`, `—`:** omit the whole `Header: value` pair. If a row has nothing but its label, say only the label.
- **`N/A`, `n/a`:** say "not applicable". Misaki reads it as the letters "N A".
- **`✅ ✓ ✔ ☑` → "yes", `❌ ✗ ✘ ✖` → "no", `⚠️` → "warning".** Drop the symbol instead if the cell has other words, for example "✅ done" becomes "done". Today Misaki maps these symbols to `❓`, which isn't in Kokoro's vocabulary, so they are **silently dropped**. A status column comes out empty.
- **Numbers and units:** Misaki handles `MB`, `GB`, `KB`, `%`, decimals and thousands separators. It drops `ms`, `→`, `±`, `~`, and `Δ`, so "12 ms" is read as "twelve". Expand these before synthesis, for example "milliseconds", "to", "plus or minus", "about", "change". This applies to prose too, not only tables.
- **Markdown inside cells:** run the existing inline cleaning (code spans, emphasis, links, path shortening) on each cell. Split cells on unescaped `|` only, because GFM allows `\|` inside cells. Turn `<br>` into ", " instead of deleting it.
- **Delimiter row** (`|:--|--:|`): never speak it. Use it to *detect* tables, which also catches tables without leading pipes.
- **Wide tables:** use the thresholds above. Don't try to read 9 headers per row.
- **First column as row header:** use it as the row's label (see Row format).
- **No header row** (GFM requires one, but agents sometimes emit an empty header like `| | |`): if every header cell is empty, read each row's values separated by commas, with no prefixes and no row numbers.

**Pauses:** in Speak's pipeline, the only strong boundary is a paragraph break, about 1.4 s of silence. Inside a paragraph, `,` `;` `:` `.` give gaps of only about 40 to 160 ms. This matches the research:

- Spiliotopoulos et al. found that a short pause between header and value and a long pause between pairs and rows helped listeners.
- Alexa recommends a 350–400 ms break between list items.

So use `:` between header and value, `;` between pairs (not `,`, because values often contain commas), `.` plus a paragraph break at the end of each row. Never use `—` or `|` as separators: the dash gave the shortest gap and the pipe is dropped.

## Evidence

### 1. How screen readers present data tables

Screen readers are interactive: the user moves cell by cell and the reader adds context. Speak is linear, so it has to put that context into the text itself. The useful parts are *what* context the readers add and *when*.

**NVDA** (NV Access):

- **Dimensions on entry.** NVDA announces "table with {N} columns and {M} rows" when it enters a new table, and "out of table" when it leaves ([`getTableInfoSpeech` in NVDA's `speech.py`](https://github.com/nvaccess/nvda/blob/af55fb6b6485f08757733aa7cd1d6f30e8a19563/source/speech/speech.py)). Another path in the same file produces "with 3 rows and 2 columns".
- **Headers only when they change.** When moving between cells, NVDA speaks the row header only when the row changes and the column header only when the column changes. Row and column numbers are optional extras, added only when "cell coordinates" reporting is on (same file, around lines 2105–2150).
- **Settings and commands.** The [NVDA User Guide](https://download.nvaccess.org/documentation/userGuide.html) lists Document Formatting options for tables: "Row/column headers" (Off, Rows, Columns, Rows and columns), "Cell coordinates", and "Cell borders". Its table commands include moving by cell (Control+Alt+arrows), "say all" in a row or column (NVDA+Control+Alt+Right/Down), and reading an entire row or column without moving (NVDA+Control+Alt+Left/Up). In Word and Excel, NVDA+Shift+C and NVDA+Shift+R mark which row or column holds the headers. That is the user doing by hand what markdown can't express.
- **Layout tables.** "Include layout tables" is off by default. Layout tables are then not reported as tables, but their content is still read as normal text.

**VoiceOver (macOS)**:

- **Row and column commands.** Apple documents VO-R to read the row header and VO-R-R to read a row from the cursor to its end. VO-C and VO-C-C do the same for columns ([Tables, graphs, and charts](https://support.apple.com/guide/voiceover/tables-graphs-and-charts-mchlp2723/mac)).
- **Header setting.** VoiceOver Utility has an announcement option, "Speak header when navigating across a table row" ([Announcements tab](https://support.apple.com/guide/voiceover/announcements-tab-cpvouverbann/mac)).
- **Blank columns.** These are skipped during arrow navigation unless table verbosity is set to High.
- **Web tables.** Apple's webpage table page covers grouping and cell navigation. It does not document announcing dimensions ([Webpage tables](https://support.apple.com/guide/voiceover/webpage-tables-vo27958/mac)).

**JAWS** (Freedom Scientific):

- **Keystrokes.** The official [Keystrokes reference](https://www.freedomscientific.com/Content/Documents/Manuals/JAWS/Keystrokes.pdf) lists Read Row (Windows+Comma or Windows+Num Pad 5), Read Column (Windows+Period), next/prior row and column (Windows+Alt+arrows), and cell movement (Alt+Ctrl+arrows).
- **Not verified.** Freedom Scientific's support site refused automated fetches (HTTP 403), so I could not read their documentation of the "Table Titles" setting or what JAWS says on entering a table. I don't make claims about either.

**Narrator** (Microsoft): has dedicated commands for Read Current Row Header, Read Current Row, Read Current Column Header, Read Current Column, and "Read Which Row and Column Narrator is in" (Ctrl+Alt+Shift+arrows and similar) ([Narrator standard keyboard layout](https://support.microsoft.com/en-US/accessibility/windows/narrator/welcome-to-the-new-standard-keyboard-layout-for-narrator)).

**TalkBack** (Android):

- **Reading controls.** Google documents "Rows and columns", "Rows" and "Columns" controls that "jump between rows and columns in a table" ([TalkBack menu and reading controls](https://support.google.com/accessibility/android/answer/6007066?hl=en)). The help page says nothing about announcing size or headers.
- **What the source shows.** TalkBack's source has spoken templates for "{n} rows", "{n} columns", "Row {n}", "Column {n}", "Row heading" and "Column heading" ([`strings_compositor.xml`](https://github.com/google/talkback/blob/229212fdf5842191d0a93fc95d9ca1423b346866/talkback/src/main/res/values/strings_compositor.xml)). It also has "Speak column header" and "Speak row header" keyboard commands ([`strings.xml`](https://github.com/google/talkback/blob/229212fdf5842191d0a93fc95d9ca1423b346866/talkback/src/main/res/values/strings.xml)).
- **Where these are used.** The strings show what TalkBack *can* say. They don't show when it says them.

**What carries over to Speak:**

- Every reader can announce table size.
- Every reader ties values to their headers, either automatically or on request.
- Row and column numbers are optional extras, not the main context.
- Reading a whole row is a first-class command in NVDA, JAWS, VoiceOver and Narrator, so row-by-row is the natural linear order.

NVDA's "speak the header only when it changes" rule means that in a row-by-row reading, where the column changes on every cell, the column header is spoken before every value. That is the header-prefixed format recommended above.

### 2. W3C/WAI and WCAG guidance

**Header association is the whole point.**

- WCAG 2.2 SC 1.3.1 requires that "information, structure, and relationships conveyed through presentation can be programmatically determined or are available in text." For data tables, the [Understanding document](https://www.w3.org/WAI/WCAG22/Understanding/info-and-relationships.html) names "the relationship of each cell to its row and/or column header" as necessary for understanding.
- Speak gets a markdown table, with no markup. The only way it can satisfy the "available in text" branch in speech is to say the header next to each value.
- The [WAI Tables tutorial](https://www.w3.org/WAI/tutorials/tables/) says: "Screen readers speak one cell at a time and reference the associated header cells, so the reader doesn't lose context."

**The specs' own speech renderings use header prefixes.** [HTML 4.01 §11.4](https://www.w3.org/TR/html401/struct/tables.html#h-11.4), "Table rendering by non-visual user agents", gives this speech rendering of a sample table:

```
Caption: Cups of coffee consumed by each senator
Summary: This table charts the number of cups ...
Name: T. Sexton,   Cups: 10,   Type: Espresso,   Sugar: No
Name: J. Dinnen,   Cups: 5,    Type: Decaf,      Sugar: Yes
```

For a table with row headers, the same section shows a full form, "Location: San Jose. Date: 25-Aug-1997. Expenses, Meals: 37.74". It then shows a "more compact" form that drops the header names of the row-header cells: "San Jose, 25-Aug-1997, Meals: 37.74". That is the basis for using the first column as an unprefixed label.

The same spec has two more points that matter here:

- **Short headers.** It defines `abbr` on header cells because "Abbreviated names should be short since user agents may render them repeatedly." Markdown has no `abbr`, so very long headers make every row long. This is an open question below.
- **Purpose and size up front.** It describes the `summary` attribute as "a summary of the table's purpose and structure for user agents rendering to non-visual media such as speech and Braille." That supports announcing structure before the content.

**CSS 2 put this into a property.** The [CSS 2 aural appendix](https://www.w3.org/TR/CSS2/aural.html) defined `speak-header: once | always`, specifying "whether table headers are spoken before every cell, or only before a cell when that cell is associated with a different header than the previous cell". It also introduced the section with "the relation between the data cells and the header cells must be expressed in a different way than by horizontal and vertical alignment." The aural media type is deprecated, but the design question it answered is the one Speak faces.

**HTML Living Standard**:

- The [table design techniques](https://html.spec.whatwg.org/multipage/tables.html) say that in speech media, cells can be distinguished "by reporting the corresponding headers before reading the cell's contents."
- Its [techniques for describing tables](https://html.spec.whatwg.org/multipage/tables.html) recommend explaining a table's purpose and basic cell structure to users who can't see it. They prefer adjusting the table so no explanation is needed, for example with headers at the top and left. Agent tables almost always have that shape: a header row, and a key in the first column.

**Captions and summaries.** The [WAI caption and summary page](https://www.w3.org/WAI/tutorials/tables/caption-summary/) says a caption "functions like a heading" and helps users "decide if they want to read it". A summary "conveys information about the organization of the data" and "is usually only needed for complex tables."

Agent tables have no caption, but the sentence before the table usually plays that role ("Here's what changed:"). The announcement only needs to add size and column names.

**Linearization and layout tables:**

- WCAG 2.2 SC 1.3.2 says "Tables and ordered lists are meaningful sequences" ([Understanding 1.3.2](https://www.w3.org/WAI/WCAG22/Understanding/meaningful-sequence.html)), so row order must be kept.
- [WCAG 1.0](https://www.w3.org/TR/WAI-WEBCONTENT/) (superseded in 2021, but the clearest statement of the idea) had checkpoints for identifying row and column headers (5.1), table summaries (5.5), and "abbreviations for header labels" (5.6). It also asked for a "linear text alternative" for tables (10.3).
- The WAI tutorial excludes layout tables. Markdown tables in agent replies are effectively always data tables, so Speak doesn't need to tell the two apart.
- WCAG lists F34 (using whitespace to format tables in plain text) as a failure. This is a reminder that the visual alignment of a markdown table carries no meaning once it is spoken.

### 3. Read-aloud products

None of the products below documents what it does with tables. I report what each source says, not observed behavior.

| Product | What its documentation says about tables |
|---|---|
| Microsoft Edge Read aloud / Reading mode | Nothing. The page covers reading the page text, voice and speed, and next/previous-paragraph controls ([Microsoft Support](https://support.microsoft.com/en-us/edge/use-immersive-reader-in-microsoft-edge)). |
| Apple Speak Screen / Speak Selection | Nothing found. The fetched guide page ([Apple Support](https://support.apple.com/guide/iphone/hear-whats-on-the-screen-or-typed-iph96b214f0/ios)) yielded only its title and navigation, so I couldn't read the body text. |
| Chrome reading mode (read aloud) | Nothing. Mentions images (show/hide) but not tables or code ([Chrome Help](https://support.google.com/chrome/answer/14218344?hl=en)). |
| Android Select to Speak | Nothing ("table" does not appear) ([Android Accessibility Help](https://support.google.com/accessibility/android/answer/7349565?hl=en)). |
| Google Read Along | Not investigated: it's a children's reading tutor, not a reader for arbitrary documents. |
| Speechify | The iOS "Auto skip content" article says you choose which content to skip, but the list of content types appears only in screenshots. Tables aren't mentioned in the text ([Speechify Help](https://intercom.help/speechifyapp/en/articles/8761214-skip-feature-on-the-ios-app)). |
| ChatGPT Read aloud | OpenAI's help center refused automated fetches (HTTP 403). A search result for its mobile app FAQ lists "Read aloud" as a response action. I found no documentation of how it handles tables or code. |

So there is no established read-aloud convention to copy. The screen-reader and W3C conventions above are the best-documented precedent.

### 4. Voice-UI guidance, research, and memory limits

**Voice-UI style guides on lists:**

- **Amazon Alexa**, [list patterns](https://developer.amazon.com/en-US/alexa/alexa-haus/patterns-and-components/patterns-lists):
  - "you can read out up to 5 distinctive, one-word list items without confusing most listeners"
  - "You may want to read out long, complex list items that have many elements one at a time"
  - "Paginate long lists. Indicate the pagination to the customer"
  - "Include a preamble that informs the customer of context such as number of items in the list"
  - "Include comma and a 350-400ms break between list items"
- **Amazon Alexa**, [design process](https://developer.amazon.com/fr/designing-for-voice/design-process): "In general, provide no more than three choices at a time." That is about choices the user must pick from, which is stricter than Speak's case.
- **Google** conversation design ([Scale your design](https://developers.google.com/assistant/conversation-design/scale-your-design)): "the spoken list is limited to 6 items (of 17 total) in order to reduce cognitive load". It also says "Don't rattle out the full list" and to point the user to the screen instead. Conversational Actions are deprecated, but the design guidance is still published.

Table rows are "long, complex list items", and the listener doesn't have to choose among them. That is why the recommended row limit (6) sits at the top of this range rather than at Alexa's 3. The "N more rows" tail is Alexa's "indicate the pagination".

**Research on speaking tables:**

- **[Spiliotopoulos, Xydas, Kouroupetroglou & Argyropoulos 2005](https://dspiliot.github.io/publications/Spiliotopoulos%20et%20al.%20-%202005%20-%20Experimentation%20on%20Spoken%20Format%20of%20Tables%20in%20Auditory%20User%20Interfaces.pdf)**, "Experimentation on Spoken Format of Tables in Auditory User Interfaces". This is the most directly relevant study.
  - **Setup.** Expert readers read a simple and a complex table two ways:
    - "freestyle", close to plain row-by-row linear reading
    - "guided", with each value prefixed by its header (`H1:D1 → H2:D2 …`)

    Five blind and five sighted listeners then rebuilt the tables in writing.
  - **Results.** For the complex table, plain linear reading scored 2.0 on the examiner's 1–5 reconstruction score; the header-prefixed reading scored 4.0. For the simple table, reconstruction was the same (4.4 both ways), but listeners rated the guided reading higher (4.0 vs 3.3).
  - **Prosody.** Human readers paused about 0.6–0.8 s after a header and 2.1–2.4 s after each data cell. "Shorter break between the two pieces of data combined with much longer pause between pairs resulted in better scoring". Larger pauses with clear "end of row" marking gave the most successful complex-table renditions. A pitch change near the end of a row was "a clear indication of the end of row."
  - **Caveats.** Small samples, Greek speech, and human readers rather than TTS.
- **[Yesilada, Stevens, Goble & Hussein 2004](https://research.manchester.ac.uk/en/publications/rendering-tables-in-audio-the-interaction-of-structure-and-readin/)**, "Rendering tables in audio: the interaction of structure and reading styles" (ASSETS 2004, [doi:10.1145/1028630.1028635](https://doi.org/10.1145/1028630.1028635)). It opens: "Tables remain a persistent problem for visually impaired people using screen readers". It proposes a table browser (EVITA) and a table *lineariser* that rewrites tables into a form screen readers handle better.
- **[Filepp, Challenger & Rosu 2002](https://research.ibm.com/publications/improving-the-accessibility-of-aurally-rendered-html-tables)** (ASSETS 2002, IBM Research). It reports that current aural table rendering "often result[s] in output that is very difficult for sight-impaired users to understand." It proposes markup that generates *prose descriptions* of tables. This supports converting tables into sentences instead of reading cells.
- **[Kildal & Brewster 2006](https://www.oneswitch.org.uk/OS-REPOSITORY/MUSEUM/VARIOUS/VR/ICDArchive2021/2006/P/2006_S07_N03_Kildal_Brewster.pdf)**, "Exploratory strategies and procedures to obtain non-visual overviews using TableVis" (ICDVRAT 2006). Its background section argues that screen readers present data "in full detail" with "little or no support to obtain overview information". It also argues that "Accessing numerical values sequentially … soon saturates the user's working memory". Its solution (interactive sonification) is out of scope, but the argument supports giving an overview first and details on request, as the `auto` mode's summary path does. Numeric benchmark tables are where reading every cell helps least.

**Memory limits:**

- [Cowan 2001](https://memory.psych.missouri.edu/assets/doc/articles/2001/cowan-bbs-2001.pdf) (*Behavioral and Brain Sciences* 24, 87–185) argues that Miller's "seven" "was meant more as a rough estimate and a rhetorical device than as a real capacity limit". The real limit is "a single, central capacity limit averaging about four chunks."
- This doesn't mean a listener can only hear 4 rows. Rows are heard and released, as in prose. It does bound what has to be held *at once*: the column names announced up front, and the pairs within one row. Hence the limits of 5 or fewer column names in the announcement and 5 or fewer columns for a full read.

### 5. Speak's pipeline: what punctuation and symbols actually do

These measurements used the installed runtime: Misaki 0.9.4 English G2P, Kokoro ONNX, voice `af_sarah`, speed 1.0. Silence is 10 ms windows with RMS below a threshold, so the figures are approximate.

**Symbols that vanish.** Misaki emits `❓` for symbols it can't pronounce. `❓` isn't in Kokoro's tokenizer vocabulary, and [`KokoroEngine.synthesize`](../../herdr_speak/daemon.py) drops tokens outside the vocabulary, so these symbols are **silent**:

- `✅`, `❌`, `✓`, `✗`
- `→`, `±`, `~`, `Δ`
- the unit `ms` (`12 ms` and `42 ms` lose the unit)
- `|`
- file extensions such as `.py` in `auth.py`

`MB`, `GB`, `KB`, `%`, `+15%`, `1.5 s`, `1,234`, `2x`, `p95` and `TBD` are read sensibly. The vocabulary's only punctuation is `; : , . ! ? — … " ( ) “ ”`.

**Pauses inside one synthesis call** (gap between two words joined by the separator, averaged over three pairs):

| Separator | Gap |
|---|---|
| space | about 30 ms |
| `—` | about 40 ms |
| `,` | about 40 ms |
| `;` | about 50 ms |
| `…` | about 60 ms |
| `?` | about 80 ms |
| `.` | about 90 ms |
| `:` | about 110 ms |

All of these are far below the 350–400 ms Alexa recommends and the 0.6–2.4 s human readers used. Kokoro shapes pitch with punctuation more than it inserts silence.

**Pauses between paragraphs.** Each Kokoro clip carries about 460 ms of leading and 700 ms of trailing near-silence. The player adds a further 250 ms `PARAGRAPH_PAUSE` ([`daemon.py`](../../herdr_speak/daemon.py)), so a paragraph boundary is about 1.4 s of silence.

That makes "one row per paragraph" the only lever that produces a clear end-of-row pause. Within a row, `:` and `;` still mark the header–value and pair boundaries through pitch and the short gaps.

Over many rows, 1.4 s per row may feel slow. If it does, the player could use a shorter pause for table rows than for prose paragraphs. That would mean adding a per-paragraph pause hint, since pauses are currently fixed.

## Open questions

- **Thresholds.** 6 rows, 5 columns, 3 preview rows and 8 columns are starting values. Listen to real agent tables (change summaries, benchmark tables) and tune them. Consider a cell-count cap as well, for example 30.
- **Header repetition vs. brevity.** With 5–6 rows, repeating every header may sound tedious. An alternative is CSS's `speak-header: once` behavior: say the headers in the announcement, then values only. Spiliotopoulos et al. found equal reconstruction for *simple* tables either way (4.4) but a listener preference for prefixes. A `compact` style for tables with 3 or fewer columns is worth trying.
- **Long headers.** HTML 4 used `abbr` for short repeated headers. Markdown has none. Speak could shorten a header after its first use, but any heuristic (first word? drop parentheticals?) needs testing.
- **Choosing the label column.** Use the first column unless it is numeric or empty. Index columns (`#`, `No.`) should probably be dropped entirely.
- **Numeric-heavy tables.** Benchmark tables may be better served by `summary` even when small, or by reading only the label column and one key metric. Kildal & Brewster's working-memory argument applies most here.
- **Other languages.** The symbol words ("yes", "no", "not applicable", "End of table") and the announcement need catalog entries for all seven languages. The pause measurements cover English Misaki only. espeak-ng (the other languages) and the macOS `say` fallback were not measured.
- **Interaction.** Screen readers let users jump by row. Speak could expose "skip table" or "next row" through its existing paragraph structure, since each row would be a paragraph. That is out of scope here.
- **Symbols outside tables.** The silent-symbol problem (`✅`, `→`, `ms`, file extensions) affects prose too. Expanding symbols in `clean_for_speech` before table handling would fix both.
- **Unverified sources.** JAWS's table announcements and "Table Titles" setting (Freedom Scientific site blocked fetches). Behavior of products whose documentation is silent: Edge, Chrome reading mode, Speechify, ChatGPT. Confirming these would mean testing them by hand.
