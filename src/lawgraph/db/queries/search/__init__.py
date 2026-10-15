"""The search of ``/api/search``: one ``SearchType`` per type (``types.py``), searched side
by side (``dispatch.py``) by the words of its fields (``clause.py``, ``text.py``), by the
persons a judgment names (``persons.py``) and by the citation a query is (``parser.py``);
each hit scored by the tier of the best way it matches (``ranking.py``). The hits of the
words searched most are kept ready to rank (``candidates.py``)."""
