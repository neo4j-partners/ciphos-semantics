# CIPHOS contracts

[`ciphos-v1.json`](ciphos-v1.json) is the versioned, read-only interface between
the lakehouse, graph, and hybrid demo workstreams. It records the destination
of every current source type, stable identifiers, snapshot compatibility, the
first projection allowlist, and the Gold result grain.

Implementation code must not invent a separate batch or snapshot convention.
An intentional contract change increments `contract_version` and is reviewed
before affected workstreams proceed. The current CSV release is a snapshot,
not effective-dated history.
