## Test strength (catchscore)

Before declaring a change done, run `catchscore` in the project root. It injects small bugs into the lines you
changed and reports the ones no test catches. If the catch score is below 80%, add tests that catch the listed
bugs (test the exact boundary or branch each bug touches) and run it again. Never weaken, skip or delete an
existing test to raise the score.
