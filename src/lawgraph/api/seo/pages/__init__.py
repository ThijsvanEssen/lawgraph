"""The server HTML of a readable address: per kind of source its title and description in
the words people search, its canonical address, its structured data (JSON-LD) and its
content with links to the sources it is connected to.

``base`` holds what every page is made of, ``titles`` the title (``core.names``, which the
API gives too) and the description of each kind of source, and one module per domain its
pages:
``laws``, ``judgments``, ``parliament`` and ``government``.
"""
