"""The parties of a judgment, read from its kop (pure: no I/O, no store).

The kop (``core.judgments.kop_lines``) names the parties between an opener ("in de zaak
van", "tussen", "in de strafzaak tegen", "Partijen:", "Uitspraak op het hoger beroep
van:") and the first section heading, one side before "tegen" or "en" and the other after
it. Around each name stand lines that are no party: where it lives, a role ("EISERS in
eerste aanleg,"), what the judgment calls it ("hierna: EBN") and who represents it
("advocaat: mr. X"). A role line holds for every party above it since the previous one.

A party gets the role the judgment states (a role line, a role behind the name, a list of
designations); else the role its anonymised name is ("[verdachte]", "[klager 1]"); else
one derived from the area of law and its side (``role_stated`` false).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from lawgraph.core.judgments import (
    AREA_ADMINISTRATIVE,
    AREA_CIVIL,
    AREA_CRIMINAL,
    area_of_law,
)

SIDE_FIRST = "first"
SIDE_SECOND = "second"
SIDE_OTHER = "other"

ROLE_PARTY = "Partij"  # no role applies

REPRESENTATIVE_LAWYER = "advocaat"
REPRESENTATIVE_AGENT = "gemachtigde"

# A role word as the judgment writes it (lower case, singular or plural, male or
# female) -> the role label.
_ROLE_WORDS = {
    "Verdachte": r"verdachten?",
    "Betrokkene": r"betrokkenen?",
    "Klager": r"klagers?|klaagsters?",
    "Veroordeelde": r"veroordeelden?|terbeschikkinggestelden?",
    "Eiser": r"eisers?|eiseres(?:sen)?|eisende\s+partij(?:en)?",
    "Gedaagde": r"gedaagden?(?:\s+partij)?",
    "Verzoeker": r"verzoekers?|verzoeksters?|verzoekende\s+partij(?:en)?|"
    r"requestrant(?:e|en|es)?",
    "Verweerder": r"verweerders?|verweersters?|verwerende\s+partij(?:en)?|"
    r"gerequestreerden?",
    "Appellant": r"appellant(?:e|en|es)?|"
    r"die\s+(?:het\s+)?hoger\s+beroep\s+heeft\s+ingesteld",
    "Geïntimeerde": r"ge[ïi]ntimeerden?",
    "Belanghebbende": r"(?:derde[-\s]?)?belanghebbenden?|"
    r"tussen(?:ge)?kom(?:en|ende)\s+partij(?:en)?|gevoegde\s+partij(?:en)?",
    "Opposant": r"opposant(?:e|en|es)?",
    "Wederpartij": r"wederpartij(?:en)?",
}


# What stands before a role word: "de verdachte", "oorspronkelijk gedaagde", "thans
# appellante", "incidenteel appellant".
_ROLE_PREFIX = re.compile(
    r"^(?:(?:de|het|als|oorspronkelijk|thans|voorheen|incidenteel|principaal|mede)\s+)*",
    re.IGNORECASE,
)


def role_label(text: str) -> str | None:
    """The role label of *text* when it opens with a role word ("eiseres in cassatie",
    "de verdachte"), else ``None``."""
    text = _ROLE_PREFIX.sub("", text.strip(" ([,.;:"))
    for label, pattern in _ROLE_WORDS.items():
        if re.match(rf"(?:{pattern})\b", text, re.IGNORECASE):
            return label
    return None


# ── line shapes ──────────────────────────────────────────────────────────────

# A word spaced out letter by letter: "t e g e n", "e i s e r e s ,", "E N"; not the
# initials of a name ("C MANAGEMENT B.V.").
_SPACED = re.compile(r"^(?:(?:[a-zäëïöüé] )+[a-zäëïöüé]|(?:[A-Z] ){2,}[A-Z])\b")


def _despace(line: str) -> str:
    """*line* with a spaced-out opening word written together ("t e g e n" is "tegen")."""
    match = _SPACED.match(line)
    if not match:
        return line
    return match[0].replace(" ", "") + line[match.end() :]


# The line that parts the sides: "tegen", "en", "en tegen", "- tegen -", "versus".
_SEPARATOR = re.compile(
    r"^[-–\s]*(?P<word>tegen|en\s*tegen|en|versus|contra)[-–\s]*:?$", re.IGNORECASE
)

# An opener: the parties follow. The role it names, if any, is theirs.
_OPENERS: tuple[tuple[re.Pattern[str], str | None, str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), role, kind)
    for pattern, role, kind in (
        # "Uitspraak op het hoger beroep van:", "op de hoger beroepen van:"
        (r"\bhoger\s+beroep(?:en)?\s+van\s*:?\s*$", "Appellant", "appeal"),
        # the case the appeal was against: "in het geding tussen:"
        (r"\bin\s+het\s+geding\s+tussen\s*:?\s*$", None, "earlier"),
        (r"\bgeding(?:en)?\s+tussen(?:\s+onder\s+meer)?\s*:?\s*$", None, "open"),
        (r"\bberoep(?:en)?\s+(?:in\s+cassatie\s+)?van\s*:?\s*$", None, "open"),
        (
            r"\b(?:verzoek(?:schrift)?|rekest)\s+(?:\w+\s+){0,3}van\s*:?\s*$",
            "Verzoeker",
            "open",
        ),
        (r"\b(?:klaagschrift|beklag)\s+(?:\w+\s+){0,3}van\s*:?\s*$", "Klager", "open"),
        (r"\bverzet\s+van\s*:?\s*$", "Opposant", "open"),
        (r"\btegen\s+de\s+verdachte\s*:?\s*$", "Verdachte", "against"),
        (r"\b(?:straf)?zaak\s+tegen\s*:?\s*$", None, "against"),
        (r"^partijen\s*:?\s*$", None, "list"),
        (
            r"^als\s+belanghebbenden?\s+(?:wordt|worden|zijn|is)\s+aangemerkt\s*:?$",
            "Belanghebbende",
            "other",
        ),
        (r"^(?:derde-?)?belanghebbenden?\s*:$", "Belanghebbende", "other"),
        (
            r"^(?:en\s*)?(?:in\s*zake|in\s+de\s+zak(?:e|en)\b(?:.*?\b(?:van|tussen)\b)?|"
            r"tussen|in\s+het\s+geding\s+tussen)\b\s*:?",
            None,
            "open",
        ),
        (
            r"\b(?:van|door)\s*:\s*$|"
            r"\b(?:tussen|inzake|in\s+de\s+zaak\s+van|betreffende|ten\s+aanzien\s+van)"
            r"\s*:?\s*$",
            None,
            "open",
        ),
        # "Conclusie inzake: [verdachte]", "CONCLUSIE inzake: Stichting X,"
        (r"\binzake\s*:", None, "open"),
        (r"^(?:van|door|tussen|in\s+de\s+zaak\s*:?)$", None, "open"),
        (r"\btegen\s*:?\s*$", None, "against"),
    )
)

# An opener that names the role: "ingediend door de verzoeker:", "strafzaak inzake de
# verdachte".
_ROLE_OPENER = re.compile(
    r"\b(?P<how>van|door|tegen|inzake|betreffende)\s+(?:de\s+)?(?P<role>[\w-]+)\s*:?\s*$",
    re.IGNORECASE,
)
# A party named in a sentence of the kop, as the Hoge Raad does in tax cases: "op het beroep
# in cassatie van [X] te [Z] (hierna: belanghebbende) tegen de uitspraak ...", "op het door
# [A] ingestelde beroep in cassatie".
_PARTY_IN_SENTENCE = (
    re.compile(
        r"\bberoep\s+in\s+cassatie\s+van\s+(?P<name>.+?)\s+tegen\s+(?:de|het|een)\s"
    ),
    re.compile(r"\bop\s+het\s+door\s+(?P<name>.+?)\s+ingestelde\s+(?:hoger\s+)?beroep"),
)

# "hierna: EBN", "hierna gezamenlijk: [eisers]", "hierna respectievelijk: de Maatschap en
# NAM", "gezamenlijk nader ook te noemen: ...", "(hierna: de verdachte)".
_ALIAS = re.compile(
    r"^\(?\s*(?P<how>hierna(?:\s+(?:ook|samen|gezamenlijk|respectievelijk|afzonderlijk|"
    r"te\s+noemen|genoemd|nader|aangeduid(?:\s+als)?))*|(?:gezamenlijk|samen)?\s*(?:nader\s+)?(?:ook\s+)?"
    r"(?:verder\s+)?te\s+noemen)\s*(?::|(?<=noemen)\s)\s*(?P<alias>.+?)\s*\)?\s*[.,;]?$",
    re.IGNORECASE,
)

# An alias in quotes ends at its closing quote when a sentence follows: "“ [eisers] ”, eiser 2
# wordt hierna aangeduid als: ...", not "‘Alegre’, ‘Rennoc’ en ‘Tregobad’".
_QUOTED = re.compile(
    r"^\s*[“\"‘']\s*(?P<alias>[^“”\"‘’']+?)\s*[”\"’'](?=\s*,?\s*\w+(?:\s+\w+){0,3}\s+"
    r"(?:wordt|worden)\b)"
)
# The legal form that ends a company name: "Maatschappij B.V.", "Shell plc".
_LEGAL_SUFFIX = re.compile(
    r"\s(?:B\.\s?V\.?|N\.\s?V\.?|V\.O\.F\.?|C\.V\.?|U\.A\.?|Ltd\.?|GmbH|S\.A\.?|"
    r"AG|SE|plc|LLC|Inc\.?)$"
)

# "advocaat: mr. X", "advocaat in de prejudiciële procedure: mr. X",
# "(gemachtigde: mr. Y)", "advocaten: mr. A en mr. B, beiden kantoorhoudende te ..."
_REPRESENTATIVE = re.compile(
    r"^\(?\s*(?P<kind>(?:proces)?advoca(?:at|te|ten)|advocaat\s+en\s+procureur|procureur|"
    r"raads(?:man|vrouw)|gemachtigden?)\b(?:[^:()]{0,60}:|\s+(?=mr\.?\s))\s*"
    r"(?P<names>.+?)\s*\)?\s*[.,;]?$",
    re.IGNORECASE,
)
# "De gemachtigde van de betrokkene is mr. R. de Nekker, kantoorhoudende te Heerenveen."
_REPRESENTATIVE_SENTENCE = re.compile(
    r"^de\s+(?P<kind>gemachtigde|advocaat|raads(?:man|vrouw))\s+van\s+.{1,60}?\s+is\s+"
    r"(?P<names>(?:mr|dr|prof)\.?\s.+?)\s*[.,;]?$",
    re.IGNORECASE,
)
_REPRESENTATIVE_TAIL = re.compile(
    r",?\s*(?:\b(?:beiden|allen|allebei|ieder)\b.*|kantoor\s*houdende.*|voormeld.*|"
    r"\b(?:te|in|uit)\s+[A-Z’'][\w’'-]*(?:\s+[A-Z][\w-]*)*\s*)$"
)

# Lines about a party that are no party: where it lives, when it was born.
_NOT_A_NAME = re.compile(
    r"^\(?\s*(?:geboren|wonende?|woonachtig|woonplaats|gevestigd|zetelende?|kantoor\s*"
    r"houdende?|die\s+(?:woont|is\s+gevestigd)|met\s+(?:statutaire\s+)?zetel|statutair|"
    r"thans|verblijvende?|zonder\s+(?:vaste|bekende)|gedetineerd|brp|v-nummer|adres|"
    r"domicilie|procederend|in\s+persoon|niet\s+verschenen|voormeld|h\.o\.d\.n|"
    r"handelend|voorheen|in\s+(?:zijn|haar)\s+hoedanigheid|ten\s+deze|tevens|"
    r"postbus|beiden?\b|allen\b|alsmede\b|die\b|verschenen|(?:te|uit|in)\s+[\[A-Z’']|"
    r"edelhoogachtba|parket\b|"
    r"(?:proces)?advoca(?:at|ten)\b|gemachtigden?\b|"
    r"(?:uitspraak|arrest|vonnis|beschikking|proces-verbaal)\b|"
    r"de\s+(?:moeder|vader|man|vrouw|ouders?|minderjarigen?|grootmoeder|grootvader|"
    r"pleegouders?)\s*[,.;]?$)",
    re.IGNORECASE,
)
# A placeholder of the anonymisation that names no party: "[adres 1]", "[BRP-adres]".
_PLACEHOLDER = re.compile(
    r"^\[\s*(?:brp|v-nummer|adres|woonplaats|geboorte|plaats|vestigingsplaats|postcode|"
    r"straat|datum|land|gemeente|nummer|telefoon|e-?mail|iban|kenteken|bsn|zaak)",
    re.IGNORECASE,
)

# A legal form alone, the name on the next line: "de stichting", "1. de publiekrechtelijke
# rechtspersoon", "de besloten vennootschap met beperkte aansprakelijkheid".
_LEGAL_FORM = (
    r"(?:[Dd]e\s+|[Hh]et\s+)?(?:rechtspersoonlijkheid\s+bezittende\s+)?"
    r"(?:besloten\s+vennootschap(?:pen)?(?:\s+met\s+beperkte\s+"
    r"aansprakelijkheid)?|naamloze\s+vennootschap(?:pen)?|gecertificeerde\s+instelling|"
    r"vennootschap\s+met\s+beperkte\s+aansprakelijkheid|stichting|vereniging(?:\s+met\s+volledige\s+"
    r"rechtsbevoegdheid)?|co[öo]peratie(?:ve\s+vereniging)?|(?:publiekrechtelijke\s+|"
    r"openbare\s+)?rechtspersoon|vennootschap(?:\s+onder\s+firma)?|"
    r"commanditaire\s+vennootschap|maatschap|onderlinge\s+waarborgmaatschappij|"
    r"(?:private|public)\s+limited\s+company|limited\s+liability\s+company)"
)
# "naar Duits recht", "naar het recht van de Kaaimaneilanden"
_JURISDICTION = (
    r"naar\s+(?:het\s+)?(?:\w+\s+)?recht(?:\s+van\s+(?:de\s+|het\s+)?[\w'’-]+"
    r"(?:\s+[A-Z][\w'’-]*){0,3})?"
)
_LEGAL_FORM_ALONE = re.compile(
    rf"^(?:{_LEGAL_FORM}\s*(?:{_JURISDICTION})?|{_JURISDICTION})\s*[,:]?$", re.I
)
# The legal form in front of the name: "de naamloze vennootschap KLM N.V."; a name that
# repeats its form keeps it ("de vereniging Vereniging Nederlandse Verkeersvliegers").
_LEGAL_FORM_PREFIX = re.compile(  # lower case: a description, not the name
    rf"^(?:{_LEGAL_FORM}(?:\s+{_JURISDICTION})?|{_JURISDICTION}|"
    r"met\s+(?:uitgesloten|beperkte)\s+aansprakelijkheid)\s+(?=\S)"
)

# "1. ", "2) ", "sub 3 ", "a. ", and the number of a section title ("1 [appellant1]").
_ENUMERATOR = re.compile(
    r"^(?:[-–•]\s*)?(?:(?:(?:sub\s*)?\d{1,3}(?:\.\d{1,3})*\s*[.):]?\s+|"
    r"(?:sub\s*)?\d{1,3}\s*[.):]|(?:[a-z]|[IVX]{1,4})[.):]\s+|[a-z]\s+(?=\[))\s*)*"
)
# Where the name ends: a comma, or a place or description behind it.
_NAME_END = re.compile(
    r"\s*(?:,|;|\s(?:wonende|wonend|woonachtig|gevestigd|kantoorhoudende|zetelende|geboren|"
    r"handelend(?:e)?|h\.o\.d\.n\.|die\s+woont|die\s+is\s+gevestigd|thans|verblijvende|"
    r"voorheen|te\s+\[|uit\s+\[|in\s+\[)\b|\s[–-]\s|\ste\s+(?=[\[A-Z'’]))",
    re.IGNORECASE,
)
_PARENTHETICAL = re.compile(r"\(([^()]*)\)")
# A line that opens with a lower-case word no name opens with: it goes on about the party
# above ("en bij de kantonrechter optrad als gedaagde", "vertegenwoordigd door ...").
_CONTINUATION = re.compile(
    r"^(?:en|op|tegen|betreffende|hierna|verder|ingeschreven|vertegenwoordigd|als|met|"
    r"alle|bij|ter|tot|na|door|voor|waarbij|welke|dat|zoals|ook|nader|onder|namens|zijnde|"
    r"respectievelijk|gezamenlijk|samen|eveneens|vanwege|conform|mede|zowel|of|toen|nu|van|"
    r"naar|ten|laatstelijk|waarvan|waar|bijgestaan|raadsheer|rechter)\b"
)
# A sentence: the judgment speaks of the parties, it does not name one. It ends the parties.
_SENTENCE_VERB = re.compile(
    r"\b(?:is|zijn|wordt|worden|zal|zullen|heeft|hebben|noemt|noemen|genoemd|aangeduid|"
    r"optrad|gekend|verschijnt|verschenen)\b",
    re.IGNORECASE,
)
PROSE_CHARS = 150
# An alias longer than this is a sentence about the names, not a name.
MAX_ALIAS_CHARS = 60
# "verzoekster 1 als: [Aandeelhouder 1]": a list of the names parties go by.
_DESIGNATION = re.compile(
    r"^(?P<who>.+?)\s+als\s*:?\s+(?P<name>.+?)\s*[.;,]?$", re.IGNORECASE
)
_CASE_NUMBER = re.compile(r"^[\w./ -]*\d[\w./ -]*$")
# A person by title: the one who acts for a party, or whose lawyers' names run on.
_PERSON = re.compile(r"(?:mr|dr|prof)\.?\s", re.IGNORECASE)


# ── the parties ──────────────────────────────────────────────────────────────


@dataclass
class _Party:
    name: str
    side: str
    role: str | None = None
    role_stated: bool = False
    alias: str | None = None
    representatives: list[dict[str, str]] = field(default_factory=list)
    # every role the judgment names for the party, in its order: "geïntimeerde in principaal
    # hoger beroep, appellante in incidenteel hoger beroep"
    stated_roles: list[str] = field(default_factory=list)

    def state(self, role: str) -> None:
        """The judgment names *role* for the party: its role when it has none stated yet,
        and one of its ``roles`` in any case."""
        if not self.role_stated:
            self.role, self.role_stated = role, True
        if role not in self.stated_roles:
            self.stated_roles.append(role)

    def as_dict(self) -> dict[str, Any]:
        role = self.role or ROLE_PARTY
        return {
            "name": self.name,
            "role": role,
            "roles": self.stated_roles or [role],
            "role_stated": self.role_stated,
            "side": self.side,
            "alias": self.alias,
            "representatives": self.representatives,
        }


def _words(name: str) -> list[str]:
    """A name as compared: its words in lower case, without an article."""
    return re.findall(r"\w+", re.sub(r"^\W*(?:de|het)\s+", "", name.lower()))


def _same(a: str, b: str) -> bool:
    """Do two names name the same party: the words of one open the other ("de minister"
    and "de minister van Financiën"; not "[eiser 1]" and "[eiser 10]")?"""
    wa, wb = _words(a), _words(b)
    shorter = min(len(wa), len(wb))
    return shorter > 0 and wa[:shorter] == wb[:shorter]


def _anonymised_role(name: str) -> str | None:
    """The role an anonymised name is: "[verdachte]", "[klager 1]", "[Appellante]"."""
    match = re.fullmatch(r"\[\s*([^\]]+?)\s*\]", name)
    return role_label(re.sub(r"\d+$", "", match[1])) if match else None


def _clean(text: str) -> str:
    """*text* without the punctuation around it: "[verdachte] ," is "[verdachte]"."""
    text = re.sub(r"\s+", " ", text).strip(" ,;:\t")
    if text.endswith(")") and text.count(")") > text.count("("):
        text = text[:-1].rstrip(" ,;:")
    # a closing dot, unless it ends an abbreviation ("B.V.", "N.V.")
    if text.endswith(".") and text.split(" ")[-1].count(".") == 1:
        text = text[:-1].rstrip(" ,")
    return text


def _representatives(kind: str, names: str) -> list[dict[str, str]]:
    agent = kind.lower().startswith("gemachtig")
    role = REPRESENTATIVE_AGENT if agent else REPRESENTATIVE_LAWYER
    names = _REPRESENTATIVE_TAIL.sub("", names.strip())
    parts = re.split(
        r"\s*(?:,|\ben\b)\s*(?=(?:mr|dr|prof|drs|ing)\.?\s|[A-Z]\.)", names, flags=re.I
    )
    return [{"name": _clean(p), "role": role} for p in parts if _clean(p)]


@dataclass
class _Name:
    """What one party line says: the name and what stands behind it."""

    name: str
    role: str | None = None
    alias: str | None = None
    representatives: list[dict[str, str]] = field(default_factory=list)


def _read_name(line: str) -> _Name | None:
    """The party a line names, else ``None``."""
    text = _ENUMERATOR.sub("", line.strip())
    found = _Name(name="")
    short = (
        None  # a bare parenthetical: "(Uwv)", or where it lives: "(Verenigde Staten)"
    )
    for inner in _PARENTHETICAL.findall(text):
        inner = inner.strip()
        if rep := _REPRESENTATIVE.match(inner):
            found.representatives += _representatives(rep["kind"], rep["names"])
        elif alias := _ALIAS.match(inner):
            text_alias = _clean(alias["alias"])
            if (label := role_label(text_alias)) and not text_alias.startswith("["):
                found.role = found.role or label
            elif len(text_alias) <= MAX_ALIAS_CHARS:
                found.alias = text_alias
        elif label := role_label(inner):
            found.role = found.role or label
        elif inner and not _PLACEHOLDER.match(inner) and len(inner) <= 40:
            short = short or _clean(inner).strip("‘’“”\"'") or None
    text = _PARENTHETICAL.sub(" ", text)
    segments = [s.strip() for s in text.split(",")]
    for segment in segments[1:]:
        if label := role_label(segment):
            found.role = found.role or label
            break
    name = _NAME_END.split(text, maxsplit=1)[0]
    name = _LEGAL_FORM_PREFIX.sub("", _clean(name))
    name = _clean(name)
    if not _is_name(name):
        return None
    found.name = name
    if (
        short
        and not found.alias
        and _abbreviates(short, name)
        and not _same(short, name)
    ):
        found.alias = short
    return found


def _unquoted(text: str) -> str:
    """*text* without the quotes around it: "‘ [eisers] ’" is "[eisers]"; a quote that opens
    or closes only a part ("[de patiënte] dan wel ‘de patiënte’") stays."""
    if len(text) > 1 and text[0] in _QUOTES and text[-1] in _QUOTES:
        return text[1:-1].strip()
    return text


def _completes(name: str, line: str) -> bool:
    """Does *line* end the name of the numbered party above, broken over two lines ("2.
    Nederlandse Aardolie" / "Maatschappij B.V.")? Only a line without a number of its own that
    ends in a legal form the name lacks."""
    text = _clean(line)
    return (
        not _ENUMERATOR.match(line)[0]  # type: ignore[index]
        and bool(_LEGAL_SUFFIX.search(f" {text}"))
        and not _LEGAL_SUFFIX.search(f" {name}")
        and text[:1].isupper()
        and (name[:1].isupper() or name.startswith("["))
        and "[" not in text
        and len(text.split()) <= 4
    )


def _abbreviates(alias: str, name: str) -> bool:
    """Could *alias* be a short name of *name*: its letters in the name, in order ("AFM" of
    "Stichting Autoriteit Financiële Markten", "Uwv", "Dexia")?"""
    letters = iter(re.sub(r"\W", "", name.lower()))
    return all(c in letters for c in re.sub(r"\W", "", alias.lower()))


def _is_name(name: str) -> bool:
    return (
        2 <= len(name) <= 120
        and any(c.isalpha() for c in name)
        and not _PLACEHOLDER.match(name)
        and not _NOT_A_NAME.match(name)
        and ":" not in name
        and not _CASE_NUMBER.match(name)
    )


class _Reader:
    """Reads the parties from the lines of a kop, one line at a time."""

    def __init__(self) -> None:
        self.parties: list[_Party] = []
        self.active = False  # between an opener and the end of the party block
        self.side = SIDE_FIRST
        self.opener_role: str | None = None
        self.kind = "open"
        self.saw_against = False
        self.since_role: list[_Party] = []  # the parties a role line holds for
        self.group: list[_Party] = []  # the parties an alias or a representative is of
        self.appeal = False  # an appeal was named: its earlier case adds counterparties
        self.designations = False  # after "als volgt worden aangeduid:"
        # the parties of the representative line above, and what it calls them
        self.represented: list[_Party] = []
        self.represented_as = ""
        # the party the line above named after its number ("2. Nederlandse Aardolie")
        self.numbered: _Party | None = None

    def read(self, line: str) -> None:
        line = _despace(line.strip())
        numbered, self.numbered = self.numbered, None
        if not line or self._opener(line):
            return
        if _named_later(line, self.parties):
            self.active = False
            return
        legal_form = bool(_LEGAL_FORM_ALONE.match(_ENUMERATOR.sub("", line)))
        if legal_form and not self.parties:
            # "de besloten vennootschap ..." with no opener before it: the parties begin
            self.active = True
        if self.designations and not self.active:
            self._designation(line)
            return
        if not self.active or self._runs_on(line):
            return
        steps = (self._separator, self._role_line, self._alias, self._representative)
        if legal_form or any(step(line) for step in steps) or _about_a_party(line):
            return  # after a legal form alone, the name follows on the next line
        if self._ends(line):
            return
        if self.group and _PERSON.match(line):
            return  # the person who acts for the party above
        if numbered is not None and _completes(numbered.name, line):
            numbered.name = f"{numbered.name} {_clean(line)}"
            return
        count = len(self.parties)
        for part in _several(line):
            self._party(part)
        if len(self.parties) == count + 1 and _ENUMERATOR.match(line)[0]:  # type: ignore[index]
            self.numbered = self.parties[-1]

    def _runs_on(self, line: str) -> bool:
        """Does *line* go on with the names of the representative line above ("advocaten:
        mr. A en" / "mr. B,")?"""
        represented, self.represented = self.represented, []
        if not represented or not _PERSON.match(line):
            return False
        self.represented = represented
        for party in represented:
            party.representatives += _representatives(self.represented_as, line)
        return True

    def _ends(self, line: str) -> bool:
        """Does *line* end the parties: the judgment speaks of them, or announces what is
        no party ("In zijn adviserende taak is gekend:")? After a sentence that ends in a
        colon, a list of the names parties go by may follow. A lead-in to more parties
        ends nothing but names none."""
        sentence = line[0].isupper() and bool(_SENTENCE_VERB.search(line))
        if len(line) <= PROSE_CHARS and not sentence:
            return line.endswith(":")  # a lead-in: "bestaande uit de volgende groepen:"
        self.active = False
        self.designations = line.endswith(":")
        return True

    # the kinds of line

    def _opener(self, line: str) -> bool:
        if not self.parties and not self.active:
            for pattern in _PARTY_IN_SENTENCE:
                if match := pattern.search(line):
                    self._party(match["name"])
                    return True
        if (match := _ROLE_OPENER.search(line)) and (
            label := role_label(match["role"])
        ):
            self._open("against" if match["how"].lower() == "tegen" else "open", label)
            return True
        for pattern, role, kind in _OPENERS:
            match = pattern.search(line)
            if not match:
                continue
            rest = line[match.end() :].strip() if kind == "open" else ""
            if kind == "earlier" and not self.appeal:
                kind = "open"
            if (
                self.active
                and kind == "against"
                and pattern.pattern.startswith(r"\btegen")
            ):
                # "tegen" at the end of a party block parts the sides
                if not self.parties or len(line) < 12:
                    return False
            self._open(kind, role)
            if rest and not _CASE_NUMBER.match(rest):
                self._party(rest)
            return True
        return False

    def _open(self, kind: str, role: str | None) -> None:
        self.active, self.kind, self.opener_role = True, kind, role
        self.since_role, self.group = [], []
        self.saw_against = kind == "against"
        self.side = {
            "against": SIDE_SECOND,
            "earlier": SIDE_SECOND,
            "other": SIDE_OTHER,
        }.get(kind, SIDE_FIRST)
        self.appeal = self.appeal or kind == "appeal"

    def _separator(self, line: str) -> bool:
        match = _SEPARATOR.match(line)
        if not match:
            return False
        word = re.sub(r"\s+", " ", match["word"].lower())
        if word in ("tegen", "versus", "contra"):
            if not self.saw_against and self.side == SIDE_SECOND:
                # "A en B tegen C": the parties after "en" were on the first side
                for party in self.parties:
                    if party.side == SIDE_SECOND and self.kind != "earlier":
                        party.side = SIDE_FIRST
            self.saw_against = True
        if self.kind != "earlier":
            self.side = SIDE_SECOND
        self.opener_role = None
        self.since_role, self.group = [], []
        return True

    def _role_line(self, line: str) -> bool:
        text = _ENUMERATOR.sub("", line)
        label = role_label(text)
        if not label or len(text) > 120 or _is_role_name(text):
            return False
        for party in self.since_role or self.group[-1:]:
            party.state(label)
        self.since_role = []
        return True

    def _alias(self, line: str) -> bool:
        match = _ALIAS.match(line)
        if not match:
            return False
        quoted = _QUOTED.match(match["alias"])
        written = _clean(quoted["alias"] if quoted else match["alias"])
        alias = _unquoted(written)
        targets = self.group or self.parties[-1:]
        label = role_label(alias)
        if label and len(alias.split()) <= 3 and not alias.startswith("["):
            # "hierna: de verdachte": a role, no name
            for party in targets:
                party.state(label)
            return True
        if len(alias) > MAX_ALIAS_CHARS:
            return True
        how = match["how"].lower()
        names = re.split(r"\s*(?:,|\ben\b)\s*", written)
        if len(targets) > 1 and (
            "respectievelijk" in how or len(names) == len(targets)
        ):
            # "hierna respectievelijk: de Maatschap en NAM", "hierna: A en B"
            for party, name in zip(targets, names, strict=False):
                party.alias = party.alias or _unquoted(_clean(name)) or None
        elif targets:
            target = targets if re.search(r"gezamenlijk|samen", how) else targets[-1:]
            for party in target:
                party.alias = party.alias or alias
        return True

    def _representative(self, line: str) -> bool:
        match = _REPRESENTATIVE.match(line) or _REPRESENTATIVE_SENTENCE.match(line)
        if not match:
            return False
        representatives = _representatives(match["kind"], match["names"])
        self.represented, self.represented_as = (
            self.group or self.parties[-1:],
            match["kind"],
        )
        for party in self.represented:
            party.representatives += representatives
        self.group = []
        return True

    def _designation(self, line: str) -> bool:
        match = _DESIGNATION.match(_clean(line))
        if not match or not role_label(match["who"]):
            return False
        label, name = role_label(match["who"]), _clean(match["name"])
        known = next((p for p in self.parties if _same(p.name, name)), None)
        if known is None:
            number = re.search(r"\b(\d+)\b", match["who"])
            same_role = [p for p in self.parties if p.role == label or p.role is None]
            index = int(number[1]) - 1 if number else 0
            known = same_role[index] if 0 <= index < len(same_role) else None
            if known is not None:
                known.alias = name
        if known is not None and label:
            known.state(label)
        return True

    def _known(self, name: str) -> _Party | None:
        """The party *name* names again: by its name, or in the case an appeal was against
        by what the judgment calls it ("de vreemdeling") or by what it is ("de
        vreemdelingen" for [vreemdeling 1] and [vreemdeling 2])."""
        known = next((p for p in self.parties if _same(p.name, name)), None)
        if known is not None or self.kind != "earlier":
            return known
        known = next(
            (p for p in self.parties if p.alias and _same(p.alias, name)), None
        )
        words = _words(name)
        if known is None and len(words) == 1 and not name.startswith("["):
            singular = re.sub(r"(?<=[a-z]{4})e?n$", "", words[0])
            known = next((p for p in self.parties if singular in _words(p.name)), None)
        return known

    def _party(self, line: str) -> None:
        found = _read_name(line)
        if found is None:
            return
        existing = self._known(found.name)
        if existing is not None:
            # a party named again: in the earlier case of an appeal, or in a joined case
            party = existing
        else:
            party = _Party(name=found.name, side=self.side)
            self.parties.append(party)
            if self.kind == "list":
                self.side = SIDE_SECOND  # "Partijen:": the first against the rest
        if found.role:
            party.state(found.role)
        elif self.opener_role and not party.role_stated and existing is None:
            party.state(self.opener_role)
        if found.alias and not party.alias:
            party.alias = found.alias
        party.representatives += found.representatives
        if existing is None:
            self.since_role.append(party)
            self.group.append(party)


# "Partijen worden hierna Chipsoft, UMCG, Treant (sub 2 en 3) en OZG genoemd.", "Appellanten
# worden hierna 'de vrachtvliegers' genoemd, geïntimeerden KLM respectievelijk VNV."
_NAMED_LATER = re.compile(
    r"^(?P<who>\w+)\s+(?:worden|wordt)\s+hierna\s+(?P<names>.+?)\s+genoemd"
    r"(?:\s*,\s*(?P<rest>.+?))?\.?$",
    re.IGNORECASE,
)
_NAME_LIST = re.compile(r"\s*,\s*|\s+(?:en|respectievelijk)\s+")
_SUB = re.compile(r"\s*\(sub\s+([\d\s,en]+)\)\s*$", re.IGNORECASE)
_QUOTES = "'\"‘’“”"


def _named_later(line: str, parties: list[_Party]) -> bool:
    """Read a sentence that says what parties are called from here on, and give each party
    named one by one its alias. A name for a whole group ("de vrachtvliegers", "UMCG c.s.")
    is no party's alias. Whether the line holds such a sentence."""
    matches = [
        match
        for sentence in re.split(r"(?<=\.)\s+(?=[A-Z])", line)
        if (match := _NAMED_LATER.match(sentence))
    ]
    for match in matches:
        _name_parties(match, parties)
    return bool(matches)


def _name_parties(match: re.Match[str], parties: list[_Party]) -> None:
    clauses = [(match["who"], match["names"])]
    if match["rest"] and len(parts := match["rest"].split(None, 1)) == 2:
        clauses.append((parts[0], parts[1]))
    for who, names in clauses:
        if re.match(r"(?:gezamenlijk|samen)\b", names, re.IGNORECASE):
            continue
        label = role_label(who)
        targets = (
            parties
            if who.lower() in ("partijen", "zij")
            else [p for p in parties if label and p.role == label]
        )
        _name_one_by_one(targets, names)


def _split_outside_parentheses(names: str) -> list[str]:
    """*names* split at commas, "en" and "respectievelijk", not inside "(sub 2 en 3)"."""
    held = re.findall(r"\([^()]*\)", names)
    masked = re.sub(r"\([^()]*\)", "\x00", names)
    parts = _NAME_LIST.split(masked)
    restored = iter(held)
    return [re.sub("\x00", lambda _: next(restored), part) for part in parts]


def _name_one_by_one(targets: list[_Party], names: str) -> None:
    slots: list[str] = []
    for name in _split_outside_parentheses(names.strip()):
        sub = _SUB.search(name)
        name = _SUB.sub("", name).strip(_QUOTES + " ")
        count = len(re.findall(r"\d+", sub.group(1))) if sub else 1
        slots += [name] * count
    if len(slots) > 1 and len(slots) == len(targets):
        for party, name in zip(targets, slots, strict=True):
            if name and len(name) <= MAX_ALIAS_CHARS:
                party.alias = party.alias or name


def _about_a_party(line: str) -> bool:
    """Is *line* about the party above, not one of its own: where it lives, "en bij de
    kantonrechter optrad als gedaagde", "[adres 1]"?"""
    return bool(
        _NOT_A_NAME.match(line)
        or _PLACEHOLDER.match(line)
        or _CONTINUATION.match(_LEGAL_FORM_PREFIX.sub("", line))
    )


def _several(line: str) -> list[str]:
    """The parties one line names: "[appellant sub 1A] en [appellante sub 1B]" is two."""
    head = re.match(
        r"^(\[[^\]]+\](?:\s*(?:,|\ben\b)\s*\[[^\]]+\])+)", _ENUMERATOR.sub("", line)
    )
    if not head:
        return [line]
    return re.findall(r"\[[^\]]+\]", head[1])


def _is_role_name(text: str) -> bool:
    """A role word that opens a name ("de verzoeker [X], wonende ...") is no role line."""
    return bool(re.search(r"\[[^\]]+\]", text)) and not text.lstrip().startswith("(")


# ── the role a judgment does not state ───────────────────────────────────────


# A public authority as a party: the prosecution, a minister, a college, a tax inspector. A
# role derived from the area of law (verdachte, eiser, appellant) is that of the other side.
_AUTHORITY = re.compile(
    r"\b(?:officier\s+van\s+justitie|openbaar\s+ministerie|advocaat-generaal|"
    r"minister|staatssecretaris|college\s+van\s+(?:burgemeester|gedeputeerde)|"
    r"burgemeester|dagelijks\s+bestuur|heffingsambtenaar|inspecteur|korpschef|"
    r"raad\s+van\s+bestuur|belastingdienst|cjib)\b",
    re.IGNORECASE,
)
_PROSECUTION = re.compile(
    r"\b(?:officier\s+van\s+justitie|openbaar\s+ministerie|advocaat-generaal)\b",
    re.IGNORECASE,
)
ROLE_PROSECUTOR = "Officier van justitie"


def _derived_role(
    party: _Party, area: str | None, *, request: bool, appeal: bool
) -> str | None:
    if _AUTHORITY.search(party.name):
        # the role the procedure gives the authority, or none
        if area == AREA_CRIMINAL:
            return ROLE_PROSECUTOR if _PROSECUTION.search(party.name) else None
        if area == AREA_ADMINISTRATIVE and party.side == SIDE_SECOND:
            return "Verweerder"
        return None
    if area == AREA_CRIMINAL:
        return "Verdachte"
    if party.side == SIDE_OTHER:
        return "Belanghebbende"
    if area == AREA_CIVIL:
        if party.side == SIDE_FIRST:
            return "Verzoeker" if request else "Eiser"
        return "Geïntimeerde" if appeal else "Verweerder"
    if area == AREA_ADMINISTRATIVE:
        return "Appellant" if party.side == SIDE_FIRST else "Verweerder"
    return ROLE_PARTY


def read_parties(lines: list[str], subjects: list[str] | None) -> list[dict[str, Any]]:
    """The parties the kop *lines* name: ``{name, role, role_stated, side, alias,
    representatives}`` each, in the order the kop names them."""
    reader = _Reader()
    for line in lines:
        reader.read(line)
    parties = reader.parties
    for index, party in enumerate(parties):
        if not party.role_stated and (label := _anonymised_role(party.name)):
            party.state(label)
        if party.role == "Belanghebbende" and index > 0:
            party.side = SIDE_OTHER
    area = area_of_law(subjects)
    request = any(re.search(r"\bbeschikking\b", line, re.IGNORECASE) for line in lines)
    appeal = any(p.role == "Appellant" and p.role_stated for p in parties)
    for party in parties:
        if not party.role_stated:
            party.role = _derived_role(party, area, request=request, appeal=appeal)
    return [party.as_dict() for party in parties]
