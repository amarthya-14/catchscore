---
description: Check whether the tests for your current changes would actually catch bugs, and strengthen them if not
---
Run `catchscore --suggest` in the project root (use `--base main` if the work is already committed on a branch).

Then:
1. If the catch score is 80% or higher and there are no "test changes worth a second look", say so in one line and stop.
2. Otherwise, read the survivors list. Each line is a bug that was injected into the code you changed and that no test noticed.
3. If catchscore wrote suggested tests to `.catchscore/`, read them, move the ones that test real behaviour into the
   project's test suite (matching its style), and delete the rest.
4. For survivors still missed, write tests yourself: one assertion per behaviour, at the exact boundary the bug touches.
   Never weaken, skip or delete an existing test to raise the score.
5. Run `catchscore` again and report the before and after scores.
