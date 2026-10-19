"""The parties of a judgment, read from its kop (pure: no I/O, no store).

The kop (``core.judgment_paragraphs.kop_lines``) names the parties between an opener ("in de zaak
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
from enum import StrEnum
from typing import Any

from lawgraph.core.dutch_names import PLACE, TITLE
from lawgraph.core.judgment_metadata import (
    AREA_ADMINISTRATIVE,
    AREA_CIVIL,
    AREA_CRIMINAL,
    area_of_law,
)

SIDE_FIRST = "first"
SIDE_SECOND = "second"
SIDE_OTHER = "other"


class Role(StrEnum):
    """The role of a party, as the judgment's own label."""

    SUSPECT = "Verdachte"
    INVOLVED = "Betrokkene"
    COMPLAINANT = "Klager"
    CONVICT = "Veroordeelde"
    CLAIMANT = "Eiser"
    DEFENDANT = "Gedaagde"
    APPLICANT = "Verzoeker"
    RESPONDENT = "Verweerder"
    APPELLANT = "Appellant"
    APPELLEE = "Geïntimeerde"
    INTERESTED_PARTY = "Belanghebbende"
    OPPONENT = "Opposant"
    COUNTERPARTY = "Wederpartij"
    PROSECUTOR = "Officier van justitie"
    PARTY = "Partij"  # no role applies


REPRESENTATIVE_LAWYER = "advocaat"
REPRESENTATIVE_AGENT = "gemachtigde"
REPRESENTATIVE_COUNSEL = "raadsman"  # of a suspect, in a criminal case only


def representative_role(word: str | None, *, criminal: bool) -> str | None:
    """The role the text's *word* gives one who acts for a party ("advocaat", "zijn
    gemachtigde", "raadsvrouw"), else ``None``; a raadsman outside a criminal case is a
    gemachtigde."""
    word = (word or "").lower()
    if word.startswith("advoca"):
        return REPRESENTATIVE_LAWYER
    if word.startswith("gemachtig"):
        return REPRESENTATIVE_AGENT
    if word.startswith("raads"):
        return REPRESENTATIVE_COUNSEL if criminal else REPRESENTATIVE_AGENT
    return None


def representative(
    name: str, role: str, place: str | None = None, capacity: str | None = None
) -> dict[str, Any]:
    """Who acts for a party: as written up to the role behind the name ("mr. S. Kriekaard"
    of "mr. S. Kriekaard, advocaat"), the role, where they practise, what else the judgment
    calls them."""
    name = _ROLE_BEHIND.sub("", name)
    return {"name": name, "role": role, "place": place, "capacity": capacity}


# ", advocaat", ", advocaat in Arnhem" behind the name of who acts for a party.
_ROLE_BEHIND = re.compile(
    r"\s*,\s*(?i:(?:proces)?advoca(?:at|te|ten)|gemachtigden?|raads(?:man|vrouw|lieden)|"
    r"procureur)\b.*$"
)


# A role word as the judgment writes it (lower case, singular or plural, male or
# female) -> the role label.
ROLE_WORDS: dict[Role, str] = {
    Role.SUSPECT: r"verdachten?",
    Role.INVOLVED: r"betrokkenen?",
    Role.COMPLAINANT: r"klagers?|klaagsters?",
    Role.CONVICT: r"veroordeelden?|terbeschikkinggestelden?",
    Role.CLAIMANT: r"eisers?|eiseres(?:sen)?|eisende\s+partij(?:en)?",
    Role.DEFENDANT: r"gedaagden?(?:\s+partij)?",
    Role.APPLICANT: r"verzoekers?|verzoeksters?|verzoekende\s+partij(?:en)?|"
    r"requestrant(?:e|en|es)?",
    Role.RESPONDENT: r"verweerders?|verweersters?|verwerende\s+partij(?:en)?|"
    r"gerequestreerden?",
    Role.APPELLANT: r"appellant(?:e|en|es)?|"
    r"die\s+(?:het\s+)?hoger\s+beroep\s+heeft\s+ingesteld",
    Role.APPELLEE: r"ge[ïi]ntimeerden?",
    Role.INTERESTED_PARTY: r"(?:derde[-\s]?)?belanghebbenden?|"
    r"tussen(?:ge)?kom(?:en|ende)\s+partij(?:en)?|gevoegde\s+partij(?:en)?",
    Role.OPPONENT: r"opposant(?:e|en|es)?",
    Role.COUNTERPARTY: r"wederpartij(?:en)?",
}


# What stands before a role word: "de verdachte", "oorspronkelijk gedaagde", "thans
# appellante", "incidenteel appellant".
_ROLE_PREFIX = re.compile(
    r"^(?:(?:de|het|als|oorspronkelijk|thans|voorheen|incidenteel|principaal|mede)\s+)*",
    re.IGNORECASE,
)


def role_label(text: str) -> Role | None:
    """The role label of *text* when it opens with a role word ("eiseres in cassatie",
    "de verdachte"), else ``None``."""
    text = _ROLE_PREFIX.sub("", text.strip(" ([,.;:"))
    for label, pattern in ROLE_WORDS.items():
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


class OpenerKind(StrEnum):
    """What follows an opener: the parties (``open``), the other side (``against``), the
    parties of the case an appeal was against (``earlier``), parties of neither side
    (``other``), a list of parties (``list``), the appellants (``appeal``)."""

    OPEN = "open"
    AGAINST = "against"
    EARLIER = "earlier"
    OTHER = "other"
    LIST = "list"
    APPEAL = "appeal"


@dataclass(frozen=True)
class _Opener:
    pattern: re.Pattern[str]
    role: Role | None  # the role the opener names: the parties after it have it
    kind: OpenerKind
    # "tegen" at the end of a line: it opens the other side, or within a block parts them
    parts_sides: bool = False


def _opener_rule(
    pattern: str,
    role: Role | None,
    kind: OpenerKind,
    *,
    parts_sides: bool = False,
) -> _Opener:
    return _Opener(re.compile(pattern, re.IGNORECASE), role, kind, parts_sides)


# An opener: the parties follow. The role it names, if any, is theirs.
_OPENERS: tuple[_Opener, ...] = (
    # "Uitspraak op het hoger beroep van:", "op de hoger beroepen van:"
    _opener_rule(
        r"\bhoger\s+beroep(?:en)?\s+van\s*:?\s*$", Role.APPELLANT, OpenerKind.APPEAL
    ),
    # the case the appeal was against: "in het geding tussen:"
    _opener_rule(r"\bin\s+het\s+geding\s+tussen\s*:?\s*$", None, OpenerKind.EARLIER),
    _opener_rule(
        r"\bgeding(?:en)?\s+tussen(?:\s+onder\s+meer)?\s*:?\s*$", None, OpenerKind.OPEN
    ),
    _opener_rule(
        r"\bberoep(?:en)?\s+(?:in\s+cassatie\s+)?van\s*:?\s*$", None, OpenerKind.OPEN
    ),
    _opener_rule(
        r"\b(?:verzoek(?:schrift)?|rekest)\s+(?:\w+\s+){0,3}van\s*:?\s*$",
        Role.APPLICANT,
        OpenerKind.OPEN,
    ),
    _opener_rule(
        r"\b(?:klaagschrift|beklag)\s+(?:\w+\s+){0,3}van\s*:?\s*$",
        Role.COMPLAINANT,
        OpenerKind.OPEN,
    ),
    _opener_rule(r"\bverzet\s+van\s*:?\s*$", Role.OPPONENT, OpenerKind.OPEN),
    _opener_rule(
        r"\btegen\s+de\s+verdachte\s*:?\s*$",
        Role.SUSPECT,
        OpenerKind.AGAINST,
        parts_sides=True,
    ),
    _opener_rule(r"\b(?:straf)?zaak\s+tegen\s*:?\s*$", None, OpenerKind.AGAINST),
    _opener_rule(r"^partijen\s*:?\s*$", None, OpenerKind.LIST),
    _opener_rule(
        r"^als\s+belanghebbenden?\s+(?:wordt|worden|zijn|is)\s+aangemerkt\s*:?$",
        Role.INTERESTED_PARTY,
        OpenerKind.OTHER,
    ),
    _opener_rule(
        r"^(?:derde-?)?belanghebbenden?\s*:$", Role.INTERESTED_PARTY, OpenerKind.OTHER
    ),
    _opener_rule(
        r"^(?:en\s*)?(?:in\s*zake|in\s+de\s+zak(?:e|en)\b(?:.*?\b(?:van|tussen)\b)?|"
        r"tussen|in\s+het\s+geding\s+tussen)\b\s*:?",
        None,
        OpenerKind.OPEN,
    ),
    _opener_rule(
        r"\b(?:van|door)\s*:\s*$|"
        r"\b(?:tussen|inzake|in\s+de\s+zaak\s+van|betreffende|ten\s+aanzien\s+van)"
        r"\s*:?\s*$",
        None,
        OpenerKind.OPEN,
    ),
    # "Conclusie inzake: [verdachte]", "CONCLUSIE inzake: Stichting X,"
    _opener_rule(r"\binzake\s*:", None, OpenerKind.OPEN),
    _opener_rule(r"^(?:van|door|tussen|in\s+de\s+zaak\s*:?)$", None, OpenerKind.OPEN),
    _opener_rule(r"\btegen\s*:?\s*$", None, OpenerKind.AGAINST, parts_sides=True),
)
# The side the parties after an opener of a kind are on; the first unless named here.
_OPENER_SIDE = {
    OpenerKind.AGAINST: SIDE_SECOND,
    OpenerKind.EARLIER: SIDE_SECOND,
    OpenerKind.OTHER: SIDE_OTHER,
}

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
# NAM", "gezamenlijk nader ook te noemen: ...", "(hierna: de verdachte)", "(tezamen en in
# enkelvoud: Trusthave Management)".
_TOGETHER = r"(?:tezamen|samen|gezamenlijk)(?:\s+en\s+(?:ieder\s+)?in\s+enkelvoud)?"
# An alias of all the parties named since the last role: "hierna gezamenlijk", "(samen: ..)".
_GROUP = re.compile(r"gezamenlijk|samen|tezamen", re.IGNORECASE)
_ALIAS = re.compile(
    r"^\(?\s*(?P<how>hierna(?:\s+(?:ook|samen|gezamenlijk|tezamen|en\s+in\s+enkelvoud|"
    r"respectievelijk|afzonderlijk|te\s+noemen|genoemd|nader|aangeduid(?:\s+als)?))*|"
    rf"{_TOGETHER}(?=\s*:)|(?:gezamenlijk|samen)?\s*(?:nader\s+)?(?:ook\s+)?"
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
LEGAL_SUFFIX = re.compile(
    r"\s(?:B\.\s?V\.?|N\.\s?V\.?|V\.O\.F\.?|C\.V\.?|U\.A\.?|Ltd\.?|GmbH|S\.A\.?|"
    r"AG|SE|plc|LLC|Inc\.?)$"
)

# "advocaat: mr. X", "advocaat in de prejudiciële procedure: mr. X",
# "(gemachtigde: mr. Y)", "advocaten: mr. A en mr. B, beiden kantoorhoudende te ..."
_REPRESENTATIVE = re.compile(
    r"^\(?\s*(?P<kind>(?:proces)?advoca(?:at|te|ten)|advocaat\s+en\s+procureur|procureur|"
    rf"raads(?:man|vrouw)|gemachtigden?)\b(?:[^:()]{{0,60}}:|\s+(?={TITLE}))\s*"
    r"(?P<names>.+?)\s*\)?\s*[.,;]?$",
    re.IGNORECASE,
)
# "De gemachtigde van de betrokkene is mr. R. de Nekker, kantoorhoudende te Heerenveen."
_REPRESENTATIVE_SENTENCE = re.compile(
    r"^de\s+(?P<kind>gemachtigde|advocaat|raads(?:man|vrouw))\s+van\s+.{1,60}?\s+is\s+"
    rf"(?P<names>{TITLE}.+?)\s*[.,;]?$",
    re.IGNORECASE,
)
_REPRESENTATIVE_TAIL = re.compile(
    r",?\s*(?:\b(?:beiden|allen|allebei|ieder)\b.*|kantoor\s*houdend.*|voormeld.*|"
    r"advoca(?:at|ten)\b.*|"
    rf"\b(?:te|in|uit)\s+{PLACE}\s*)$"
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
_PERSON = re.compile(TITLE)


# ── the parties ──────────────────────────────────────────────────────────────


@dataclass
class Party:
    """A party of a judgment as it is read; ``as_dict`` is what is stored."""

    name: str
    side: str
    role: Role | None = None
    role_stated: bool = False
    alias: str | None = None
    representatives: list[dict[str, Any]] = field(default_factory=list)
    # every role the judgment names for the party, in its order: "geïntimeerde in principaal
    # hoger beroep, appellante in incidenteel hoger beroep"
    stated_roles: list[Role] = field(default_factory=list)

    def state(self, role: Role) -> None:
        """The judgment names *role* for the party: its role when it has none stated yet,
        and one of its ``roles`` in any case."""
        if not self.role_stated:
            self.role, self.role_stated = role, True
        if role not in self.stated_roles:
            self.stated_roles.append(role)

    def as_dict(self) -> dict[str, Any]:
        role = str(self.role or Role.PARTY)
        return {
            "name": self.name,
            "role": role,
            "roles": [str(r) for r in self.stated_roles] or [role],
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


def _anonymised_role(name: str) -> Role | None:
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


# Where the representatives practise, at the end of their line: "kantoorhoudende te Utrecht".
_REPRESENTATIVE_PLACE = re.compile(rf"\b(?:te|in)\s+(?P<place>{PLACE})\s*[.,;)]?\s*$")


def _representatives(kind: str, names: str, criminal: bool) -> list[dict[str, Any]]:
    """The persons a representative line names, with the role its word gives (a lawyer
    when it gives none: "procureur") and where they practise."""
    role = representative_role(kind, criminal=criminal) or REPRESENTATIVE_LAWYER
    place = _REPRESENTATIVE_PLACE.search(names.strip())
    names = _REPRESENTATIVE_TAIL.sub("", names.strip())
    parts = re.split(rf"\s*(?:,|\ben\b)\s*(?={TITLE}|[A-Z]\.)", names, flags=re.I)
    return [
        representative(_clean(p), role, place["place"] if place else None)
        for p in parts
        if _clean(p)
    ]


@dataclass
class _Name:
    """What one party line says: the name and what stands behind it."""

    name: str
    role: Role | None = None
    alias: str | None = None
    together: bool = False  # the alias is of the parties above too: "(samen: LS)"
    representatives: list[dict[str, Any]] = field(default_factory=list)


# The "en" that joins the next party: "[appellant 1] en" / "[appellant 2] ,".
_JOINED = re.compile(r"\s+en$")


def _read_name(line: str, criminal: bool) -> _Name | None:
    """The party a line names, else ``None``."""
    text = _ENUMERATOR.sub("", line.strip())
    found = _Name(name="")
    short = (
        None  # a bare parenthetical: "(Uwv)", or where it lives: "(Verenigde Staten)"
    )
    for inner in _PARENTHETICAL.findall(text):
        inner = inner.strip()
        if rep := _REPRESENTATIVE.match(inner):
            found.representatives += _representatives(
                rep["kind"], rep["names"], criminal
            )
        elif alias := _ALIAS.match(inner):
            text_alias = _clean(alias["alias"])
            if (label := role_label(text_alias)) and not text_alias.startswith("["):
                found.role = found.role or label
            elif len(text_alias) <= MAX_ALIAS_CHARS:
                found.alias = text_alias
                found.together = bool(_GROUP.search(alias["how"]))
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
    name = _clean(_JOINED.sub("", name))
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
        and bool(LEGAL_SUFFIX.search(f" {text}"))
        and not LEGAL_SUFFIX.search(f" {name}")
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

    def __init__(self, *, criminal: bool) -> None:
        self.criminal = criminal  # a raadsman is one only in a criminal case
        self.parties: list[Party] = []
        self.active = False  # between an opener and the end of the party block
        self.side = SIDE_FIRST
        self.opener_role: Role | None = None
        self.kind = OpenerKind.OPEN
        self.saw_against = False
        self.since_role: list[Party] = []  # the parties a role line holds for
        self.group: list[Party] = []  # the parties an alias or a representative is of
        self.appeal = False  # an appeal was named: its earlier case adds counterparties
        self.designations = False  # after "als volgt worden aangeduid:"
        # the parties of the representative line above, and what it calls them
        self.represented: list[Party] = []
        self.represented_as = ""
        # the party the line above named after its number ("2. Nederlandse Aardolie")
        self.numbered: Party | None = None

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
            party.representatives += _representatives(
                self.represented_as, line, self.criminal
            )
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
            against = match["how"].lower() == "tegen"
            self._open(OpenerKind.AGAINST if against else OpenerKind.OPEN, label)
            return True
        for opener in _OPENERS:
            match = opener.pattern.search(line)
            if not match:
                continue
            kind = opener.kind
            rest = line[match.end() :].strip() if kind == OpenerKind.OPEN else ""
            if kind == OpenerKind.EARLIER and not self.appeal:
                kind = OpenerKind.OPEN
            if self.active and opener.parts_sides:
                # "tegen" at the end of a party block parts the sides
                if not self.parties or len(line) < 12:
                    return False
            self._open(kind, opener.role)
            if rest and not _CASE_NUMBER.match(rest):
                self._party(rest)
            return True
        return False

    def _open(self, kind: OpenerKind, role: Role | None) -> None:
        self.active, self.kind, self.opener_role = True, kind, role
        self.since_role, self.group = [], []
        self.saw_against = kind == OpenerKind.AGAINST
        self.side = _OPENER_SIDE.get(kind, SIDE_FIRST)
        self.appeal = self.appeal or kind == OpenerKind.APPEAL

    def _separator(self, line: str) -> bool:
        match = _SEPARATOR.match(line)
        if not match:
            return False
        word = re.sub(r"\s+", " ", match["word"].lower())
        if word in ("tegen", "versus", "contra"):
            if not self.saw_against and self.side == SIDE_SECOND:
                # "A en B tegen C": the parties after "en" were on the first side
                for party in self.parties:
                    if party.side == SIDE_SECOND and self.kind != OpenerKind.EARLIER:
                        party.side = SIDE_FIRST
            self.saw_against = True
        if self.kind != OpenerKind.EARLIER:
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
            target = targets if _GROUP.search(how) else targets[-1:]
            for party in target:
                party.alias = party.alias or alias
        return True

    def _representative(self, line: str) -> bool:
        match = _REPRESENTATIVE.match(line) or _REPRESENTATIVE_SENTENCE.match(line)
        if not match:
            return False
        representatives = _representatives(match["kind"], match["names"], self.criminal)
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

    def _known(self, name: str) -> Party | None:
        """The party *name* names again: by its name, or in the case an appeal was against
        by what the judgment calls it ("de vreemdeling") or by what it is ("de
        vreemdelingen" for [vreemdeling 1] and [vreemdeling 2])."""
        known = next((p for p in self.parties if _same(p.name, name)), None)
        if known is not None or self.kind != OpenerKind.EARLIER:
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
        found = _read_name(line, self.criminal)
        if found is None:
            return
        existing = self._known(found.name)
        if existing is not None:
            # a party named again: in the earlier case of an appeal, or in a joined case
            party = existing
        else:
            party = Party(name=found.name, side=self.side)
            self.parties.append(party)
            if self.kind == OpenerKind.LIST:
                self.side = SIDE_SECOND  # "Partijen:": the first against the rest
        if found.role:
            party.state(found.role)
        elif self.opener_role and not party.role_stated and existing is None:
            party.state(self.opener_role)
        party.representatives += found.representatives
        if existing is None:
            self.since_role.append(party)
            self.group.append(party)
        for named in self.group if found.together else [party]:
            named.alias = named.alias or found.alias


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


def _named_later(line: str, parties: list[Party]) -> bool:
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


def _name_parties(match: re.Match[str], parties: list[Party]) -> None:
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


def _name_one_by_one(targets: list[Party], names: str) -> None:
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


# What the party above is and where: a few words in lower case before its place, "notaris
# te [plaats]", "oud-toegevoegd notaris te [plaats]", "gerechtsdeurwaarder in Utrecht". A
# name is capitalised or anonymised.
_CAPACITY = re.compile(r"^[a-zà-ÿ]+(?:[- ][a-zà-ÿ]+){0,2}\s+(?:te|in)\s+[\[A-Z’']")


def _about_a_party(line: str) -> bool:
    """Is *line* about the party above, not one of its own: where it lives, what it is
    ("notaris te [plaats]"), "en bij de kantonrechter optrad als gedaagde", "[adres 1]"?"""
    return bool(
        _NOT_A_NAME.match(line)
        or _CAPACITY.match(_ENUMERATOR.sub("", line))
        or _PLACEHOLDER.match(line)
        or _CONTINUATION.match(_LEGAL_FORM_PREFIX.sub("", line))
    )


# Two parties on one line, each with where it is seated or lives: "Trusthave Management
# B.V., gevestigd in Den Haag, en [appellant], wonend in [woonplaats] (...)".
_SEAT = r"(?:gevestigd|wonende?|woonachtig)\s+(?:in|te)\s+"
_SEATED_PAIR = re.compile(
    rf"^(?P<first>[^,()]+,\s*{_SEAT}[^,()]+?)\s*,?\s+en\s+"
    rf"(?P<rest>(?:\[|[A-Z])[^,()]*,\s*{_SEAT}.+)$"
)


def _several(line: str) -> list[str]:
    """The parties one line names: "[appellant sub 1A] en [appellante sub 1B]" is two, and
    so is "A B.V., gevestigd in X, en [B], wonend in Y"."""
    text = _ENUMERATOR.sub("", line)
    if pair := _SEATED_PAIR.match(text):
        return [pair["first"], *_several(pair["rest"])]
    head = re.match(r"^(\[[^\]]+\](?:\s*(?:,|\ben\b)\s*\[[^\]]+\])+)", text)
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


def _derived_role(
    party: Party, area: str | None, *, request: bool, appeal: bool
) -> Role | None:
    if _AUTHORITY.search(party.name):
        # the role the procedure gives the authority, or none
        if area == AREA_CRIMINAL:
            return Role.PROSECUTOR if _PROSECUTION.search(party.name) else None
        if area == AREA_ADMINISTRATIVE and party.side == SIDE_SECOND:
            return Role.RESPONDENT
        return None
    if area == AREA_CRIMINAL:
        return Role.SUSPECT
    if party.side == SIDE_OTHER:
        return Role.INTERESTED_PARTY
    if area == AREA_CIVIL:
        if party.side == SIDE_FIRST:
            return Role.APPLICANT if request else Role.CLAIMANT
        return Role.APPELLEE if appeal else Role.RESPONDENT
    if area == AREA_ADMINISTRATIVE:
        return Role.APPELLANT if party.side == SIDE_FIRST else Role.RESPONDENT
    return Role.PARTY


def read_parties(lines: list[str], subjects: list[str] | None) -> list[dict[str, Any]]:
    """The parties the kop *lines* name: ``{name, role, role_stated, side, alias,
    representatives}`` each, in the order the kop names them."""
    area = area_of_law(subjects)
    reader = _Reader(criminal=area == AREA_CRIMINAL)
    for line in lines:
        reader.read(line)
    parties = reader.parties
    for index, party in enumerate(parties):
        if not party.role_stated and (label := _anonymised_role(party.name)):
            party.state(label)
        if party.role == Role.INTERESTED_PARTY and index > 0:
            party.side = SIDE_OTHER
    request = any(re.search(r"\bbeschikking\b", line, re.IGNORECASE) for line in lines)
    appeal = any(p.role == Role.APPELLANT and p.role_stated for p in parties)
    for party in parties:
        if not party.role_stated:
            party.role = _derived_role(party, area, request=request, appeal=appeal)
    return [party.as_dict() for party in parties]
