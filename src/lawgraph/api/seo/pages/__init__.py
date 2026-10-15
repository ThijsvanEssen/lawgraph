"""The server HTML of a readable address: per kind of source its title and description in
the words people search, its canonical address, its structured data (JSON-LD) and its
content with links to the sources it is connected to.

``base`` holds what every page is made of, ``titles`` the title of each kind of source
(which the SPA shows too, from ``title_of``), and one module per domain its pages:
``laws``, ``judgments``, ``parliament`` and ``government``.
"""
