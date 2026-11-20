Schema v1 is defined by the SQLAlchemy models and created at startup via Base.metadata.create_all. For this local small application no destructive migration is run. Back up named db-data before modifying schemas.

v2 adds the dispatch-replay tables (`trial_orders`, `shift_quotas`, `replays`) defined in `src/models/replay.py`. `create_all` adds the new tables on an existing database and does not touch existing rows. Rolls back by dropping those three tables; existing studies, observations and runs are unaffected.
