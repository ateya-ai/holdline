# Decision rules

Evaluate in this order:

1. Either finding missing, invalid, or ERROR: INCOMPLETE, including BLOCK plus ERROR.
2. Otherwise, either finding BLOCK: BLOCKED.
3. Otherwise, both findings CLEAR: READY_FOR_REVIEW.

The release_executed field is always false. The Python rules and validated snapshots determine the result. Model wording cannot change it.
