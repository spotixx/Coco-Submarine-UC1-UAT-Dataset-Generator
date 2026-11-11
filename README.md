# Coco-Submarine-UC1-UAT-Dataset-Generator

Generates synthetic UC1 / Submarine weekly-submission datasets for UAT, for **any number of banks**. You give it a bank/BIC mapping file. It writes one submission CSV per bank, the expected shared-list export, and a README describing every scenario in the dataset.

```
python generate.py <mapping.csv> [--rows-per-bank N] [--out <run folder>]
```

## Requirements

- Python 3.8 or newer.
- No third-party packages. `requirements.txt` only states this, so `pip install -r requirements.txt` installs nothing.
- The folder is self-contained: it reads only the mapping file you pass and its own `templates/`, so it can be copied anywhere.

## Running in a virtual environment

Run these from the repository root, the folder that contains `generate.py`.

1. **Create the environment once.** It goes in `.venv/` next to `generate.py`.

   ```
   python -m venv .venv
   ```

   On macOS or Linux, use `python3` if `python` isn't found.

2. **Activate it.** Do this in every new terminal.

   | Shell | Command |
   |---|---|
   | Windows PowerShell | `.venv\Scripts\Activate.ps1` |
   | Windows cmd | `.venv\Scripts\activate.bat` |
   | Git Bash on Windows | `source .venv/Scripts/activate` |
   | macOS / Linux | `source .venv/bin/activate` |

   The prompt then starts with `(.venv)`.

   If PowerShell says "running scripts is disabled on this system", allow scripts for this terminal only and activate again:

   ```
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   ```

3. **Check the version and install.**

   ```
   python --version                  # must be 3.8 or newer
   pip install -r requirements.txt   # installs nothing: standard library only
   ```

4. **Run the generator.**

   ```
   python generate.py <mapping.csv> [--rows-per-bank N]
   ```

5. **Leave the environment** when you're done:

   ```
   deactivate
   ```

You can also skip activation and call the environment's Python directly: `.venv\Scripts\python.exe generate.py <mapping.csv>` on Windows, or `.venv/bin/python generate.py <mapping.csv>` on macOS and Linux.

## Folder layout

```
Coco-Submarine-UC1-UAT-Dataset-Generator/
  README.md                this file
  generate.py              the generator (the built-in MO list is defined at the top)
  requirements.txt         standard library only
  templates/
    dataset_README.md      the README written into every generated dataset
  generated_datasets/      created by the first run; one subfolder per run
  .venv/                   your virtual environment, if you create one (see above)
```

## Input: the mapping file

A CSV with exactly this header:

```
bic,bank_name,bank_id
COBADEFF,Commerzbank AG,commerzbank
COBADEBB,Commerzbank AG,commerzbank
DEUTDEFF,Deutsche Bank AG,deutsche_bank
WELADEDD,Sparkasse,sparkasse
```

- **Every `bank_id` in the file is a participating bank.** Bank order is the order in which each `bank_id` first appears. The named scenario accounts are built from these positions: bank 1, bank 2, bank 3 and so on.
- **BIC8 only.** Every BIC must be 8 characters (`[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}`). BIC11 is not supported.
- **Each BIC appears once.** A bank can have any number of BICs, and they are all equal: there is no primary or secondary BIC.
- **`bank_id`** is lower-case letters, digits or `_`, because it becomes the file name `data/<bank_id>.csv`.
- **`bank_name`** is the display name used in the export. Each `bank_id` has exactly one non-empty name, and no two banks share one.
- **3 to 99 banks.**
- **At least 6 of the 12 outside BICs** (see [What every dataset contains](#what-every-dataset-contains)) must not be in the mapping.

The run stops with an error, and writes nothing, if any of these rules is broken.

## Options

| Option | Default | Meaning |
|---|---|---|
| `--rows-per-bank N` | `5000` | Every bank's file gets exactly N rows. |
| `--out <folder>` | `generated_datasets/<YYYYMMDD-HHMMSS>_n<banks>_r<N>_<mapping name>/` | The run folder to create. It must not exist: a run never overwrites anything. |

Example: `python generate.py ../bank-bics-10.csv --rows-per-bank 8000` writes `generated_datasets/20261110-143205_n10_r8000_bank-bics-10/`.

## Output: one run folder

```
README.md                                    every number, block and named account in this dataset
bank_bic_mapping_latest.csv                  the input mapping, copied unchanged
data/<bank_id>.csv                           one submission file per bank, exactly N rows
expected_results/fraud_accounts_export.csv   the expected export, one row per account
```

There is always exactly one cycle, so there is no `cycle_1/` folder. The data files use the UC1 submission format `Account Number,BIC,Time Added,Modi Operandi,Priority Processing`.

The export has the following columns:
- `Account Number, Holding Bank BIC, Number of Reports, Priority Processing`
- one `Report i {Reporting Bank, Time, Modus Operandi, Priority Processing}` group for each report, for i = 1 up to the largest number of reporters in the dataset.

## What every dataset contains

| Block | Size |
|---|---|
| 2-bank corroboration | every pair of banks, about 20 % of each bank's rows |
| 3-bank corroboration | about 6 % of each bank's rows, with priority in thirds: one True (OR gives Yes), all False, all True |
| 4- to n-bank corroboration | 0.6 % of N accounts for each reporter count from 4 to n, above the 3-report cap of production BUG-005. Expected results are uncapped |
| Single reporter | the rest of each bank's rows: 75 % held at the bank's own BICs, 10 % at another participating bank, 15 % outside the mapping |

- **Named scenario accounts** pin one case each:
  - two-bank corroboration;
  - held at another participating bank;
  - held outside the participating banks;
  - priority OR, all False and all True;
  - several MOs in one row;
  - an MO containing a comma;
  - a non-ASCII MO;
  - MO-union dedup;
  - tied timestamps, where report groups fall back to display name, using a pair whose roster order is the opposite of their name order when the mapping has one;
  - exactly 3 reporters;
  - a single reporter;
  - upper-case `TRUE`.
  - With 4 or more banks, add 4 reporters. With 5 or more, add all n reporters.
- **Every 10th account in each multi-reporter block** has tied timestamps.
- **One bank writes `TRUE`/`FALSE`** and the others write `True`/`False`. That bank is `sparkasse` when it is in the mapping, otherwise the last bank.
- **MOs come from one built-in list** shared by every bank (`MOS` in `generate.py`). It includes comma and non-ASCII values. No external MO list is read or written.
- **Accounts held outside the participating banks** use a fixed list of 12 BICs, minus any the mapping contains. At least 6 must remain.
- **No account repeats within a bank's file.** An account has one BIC everywhere it appears.
- **Account numbers** are `<BIC>` + `66` + the 2-digit bank count + a 10-digit counter, 22 characters in total.

The generated dataset README lists the exact counts, every named account with its expected values, and the aggregation rules the export follows.

## Determinism and regenerating

The random generator is seeded from the mapping file's bytes and N, and the data never reads the clock. On the same Python version, the same mapping and N therefore always produce byte-identical files: only the default folder name contains a timestamp. To regenerate a run, pass its own copy of the mapping:

```
python generate.py generated_datasets/<run>/bank_bic_mapping_latest.csv --rows-per-bank <its N>
```

Changing either the mapping or N changes the whole dataset, including the banks that were already there.

## Checks

**Before a run writes anything**, it validates the mapping and the plan:
- N must be large enough for the number of banks. The error gives the smallest N that works for that mapping. For 10 banks it is around 40 to 45, depending on the mapping.
- The rows must fit one week's distinct timestamps, about `banks × N ≤ 560,000`.

**After writing**, it reads every file back from disk and asserts all of the following:
- each file has exactly N rows;
- there are no repeats within a file;
- each file holds only its own bank's reports;
- each account has one BIC;
- every BIC is 8 characters and comes from the mapping or the outside list;
- account numbers are 22 characters and start with their BIC;
- every MO passes the platform's MO validator regex;
- boolean casing is correct for each bank;
- the priority thirds hold in every block of 3 or more reporters;
- every named account has its expected values;
- every pair of banks corroborates at least once;
- every report count from 1 to n occurs;
- the data aggregates exactly to the expected export;
- aggregation is idempotent;
- the copied mapping is byte-identical to the input.

If any check fails, the run folder is deleted and the error is shown.

## Reading the run summary

When every check passes, the run prints a summary and then `wrote <run folder>`. The numbers are counted from the files on disk. The dataset README shows the same numbers, with descriptive labels, in its "Size", "Reports per account" and "Blocks" tables.

Example: `python generate.py mapping.csv`, where `mapping.csv` is the 4-line example from [Input: the mapping file](#input-the-mapping-file), saved with LF line endings. It has 3 banks and uses the default of 5,000 rows per bank.

```
banks                3
rows_per_bank        5000
rows                 15000
accounts             12889
fan_in               {1: 11082, 2: 1503, 3: 304}
blocks               {'named': 14, 'pair': 1500, 'k3_one_true': 100, 'k3_all_false': 100, 'k3_all_true': 100, 'own': 8309, 'cross': 1107, 'outside': 1659}
held_outside         2113
priority_yes         1632
tied                 181
multi_mo             6268
mo_union_collapsed   12
comma_mo_rows        1507
distinct_bics_used   16
```

Every 3-bank mapping at N = 5,000 gives the same `accounts`, `fan_in`, `blocks`, `held_outside` and `tied`. The other counters are random: they depend on the mapping file's exact bytes, so even CRLF instead of LF line endings changes them.

In the tables below, n is the number of banks and N is the rows per bank.

### Size

| Field | Meaning | In the example |
|---|---|---|
| `banks` | The number of banks in the mapping. Each one gets a `data/<bank_id>.csv`. | 3 |
| `rows_per_bank` | The number of rows in every bank's file: the `--rows-per-bank` value. | 5,000 |
| `rows` | `banks` × `rows_per_bank`: every row in every file. | 15,000 |
| `accounts` | The number of distinct account numbers, which is also the number of rows in the expected export. It is lower than `rows`, because an account reported by k banks has one row in each of those k files. | 12,889 |
| `fan_in` | Accounts by the number of banks that reported them, as `{reports: accounts}`. This is the export's `Number of Reports`. Reports × accounts, summed, equals `rows`. | 11,082×1 + 1,503×2 + 304×3 = 15,000 |

### `blocks`: why each account was created

Every account belongs to exactly one block, so the block counts add up to `accounts`.

| Block | Reporting banks | How many | What it tests |
|---|---|---|---|
| `named` | 1 to n | 14, plus 1 with 4 or more banks, plus 1 more with 5 or more | the fixed scenario accounts, listed with their expected values in the dataset README |
| `pair` | 2 | `ceil(0.20 × N / (n − 1))` for every pair of banks: 500 per pair in the example | two-bank corroboration |
| `k3_one_true`, `k3_all_false`, `k3_all_true` | 3 | together about 6 % of each bank's rows, split into equal thirds | priority OR: one True gives Yes, all False gives No, all True gives Yes |
| `k4_…` to `kn_…` | 4 to n | 0.6 % of N accounts for each reporter count, in the same thirds; only with 4 or more banks | more reports than production's cap of 3 (BUG-005) |
| `own` | 1 | 75 % of each bank's leftover rows | an account held at one of the reporting bank's own BICs |
| `cross` | 1 | 10 % of the leftover rows | an account held at another participating bank, which doesn't report it |
| `outside` | 1 | 15 % of the leftover rows | an account held at a BIC that isn't in the mapping |

A bank's leftover rows are N minus its rows in the named and multi-reporter blocks. Filling the leftover is what gives every file exactly N rows.

Some `fan_in` counts are slightly higher than the matching blocks, because some named accounts have several reporters. The named accounts add:
- 7 accounts with 1 report;
- 3 with 2 reports;
- 4 with 3 reports;
- 1 with 4 reports, when there are 4 or more banks;
- 1 with n reports, when there are 5 or more banks.

In the example, the 2-report count is 1,500 `pair` accounts + 3 named = 1,503.

### Scenario coverage

| Field | Meaning | In the example |
|---|---|---|
| `held_outside` | All accounts whose holding BIC isn't in the mapping, whatever their block. See [`outside` and `held_outside`](#outside-and-held_outside) below. | 2,113 |
| `priority_yes` | Accounts whose export Priority Processing is `Yes`, because at least one reporting bank said True. The `k…` blocks set priority by thirds and the named accounts set it explicitly. Every other row is True with a 10 % chance. | 1,632 |
| `tied` | Multi-reporter accounts where every reporter submitted in the same second. They test the fallback sort of report groups by bank name. Every 10th account in each multi-reporter block is tied, plus one named account. | 150 + 30 + 1 = 181 |
| `multi_mo` | Accounts with more than one distinct MO in total, either because one row lists several (`A;B`) or because the banks used different MOs. | 6,268 |
| `mo_union_collapsed` | Multi-reporter accounts with fewer distinct MOs than reports. This can only happen when at least two banks gave the same MO, so it shows that duplicate MOs are removed when reports are merged. | 12 |
| `comma_mo_rows` | **Rows**, not accounts, whose MO contains a comma, such as `Betrug, unspezifiziert`. They test CSV quoting. | 1,507 |
| `distinct_bics_used` | The number of different holding BICs across all accounts. The maximum is the mapping's BICs plus the outside BICs. The data doesn't have to use every BIC in the mapping. | 16 (4 + 12) |

### `outside` and `held_outside`

Both count accounts held at a BIC that isn't in the mapping, but not the same accounts:
- **`outside`** is one block: accounts that **one** bank reported.
- **`held_outside`** counts **every** account held outside, including those that several banks reported.

`outside` is part of `held_outside`:

| Part of `held_outside` | Reporting banks | In the example |
|---|---|---|
| the whole `outside` block | 1 | 1,659 |
| every 4th `pair` account | 2 | 375 |
| every 4th account in the `k…` blocks | 3 to n | 75 |
| named accounts held outside: 4, or 5 with 5 or more banks | 1 to n | 4 |
| **`held_outside`** | | **2,113** |

The multi-reporter part tests the case where several banks report an outside-held account. The export must show it as one row, with that outside BIC as the Holding Bank BIC.

## Limits

| Limit | Why | To go further |
|---|---|---|
| 3 to 99 banks | no 2-bank mode; the bank count is 2 digits in the account number. 99 banks × 5,000 rows takes about a minute | add when needed |
| BIC8 only | by design | — |
| about `banks × N ≤ 560,000` rows | the bulk times must be distinct seconds inside one week | widen `T_NATURAL` / `T_TIED` in `generate.py` |
| one cycle | multi-cycle scenarios (S1, S3–S6, S8) are out of scope | — |
| account numbers repeat between runs with the same bank count | `<BIC>66<nn><counter>` restarts at the same counters every run, so two different 10-bank runs can share account numbers with different content | load one run at a time, or give each run its own infix if two must coexist |
