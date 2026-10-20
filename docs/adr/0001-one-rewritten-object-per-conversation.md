# One rewritten object per conversation

Each /ask Conversation is logged as a single Cloud Storage object, `conversations/<uuid>.json`, that the agent reads, extends with the new Turn and writes back on every Turn, guarded by a generation precondition.

Cloud Storage objects can't be appended to, so the alternatives were one object per Turn (append-only, simple, but a Conversation becomes a folder) or having the browser send the whole thread each time (no read needed, but the log then trusts the client). We wanted one file per Conversation that is easy to open and can't be forged by the browser, and accepted the extra read per Turn, plus a retry when two Turns of one Conversation race.

Changing this later means rewriting or migrating every stored log.
