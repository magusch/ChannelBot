"""Venue matching: event address/title → Place id. Pure functions, no DB."""

import re
from dataclasses import dataclass, field

MIN_KEYWORD_LENGTH = 4
MIN_ALIAS_LENGTH = 5

_NON_WORD_RE = re.compile(r"[^a-zа-я0-9]+")
_DIGIT_LETTER_RE = re.compile(r"(?<=\d)(?=[a-zа-я])|(?<=[a-zа-я])(?=\d)")
_DOUBLE_RE = re.compile(r"(.)\1")
_PAREN_RE = re.compile(r"\([^)]*\)")

# Words that are never a street name: street types, house parts, city, metro.
_ADDRESS_NOISE = frozenset(
    "ул улица у пр просп проспект т пер переулок наб набережная р река реки "
    "кан канал канала б бр бул бульвар пл площадь ш шоссе аллея ал проезд туп "
    "тупик д дом стр строение корп корпус к лит литер литера пом помещение "
    "помещ оф офис эт этаж в о во п с остров острова васильевского "
    "петроградской стороны сторона г город гор спб санкт петербург "
    "петербурга россия рф казань м метро им имени я й ая ий ой ый е".split()
)
_ORDINAL_SUFFIXES = frozenset("я й ая ий ой ый е го".split())
_STREET_MODIFIERS = frozenset("больш мал средн верхн нижн нов стар".split())
_CORPUS_WORDS = frozenset(("к", "корп", "корпус"))
# Lines and Bolshoy/Maly prospekt exist on both Vasilyevsky and Petrogradka.
_ISLAND_RES = (
    ("во", re.compile(r"\b[Вв]\.\s?[Оо]\b|\bВО\b|васильевск\w*\s+остров", re.I)),
    ("пс", re.compile(r"\b[Пп]\.\s?[Сс]\b|\bПС\b|петроградск\w*\s+сторон", re.I)),
)

# Leading venue-type words dropped to get a bare name alias:
# «Клуб «Money Honey»» → «money honey».
_VENUE_TYPE_WORDS = frozenset(
    "клуб бар кафе ресторан паб кофейня театр галерея арт пространство "
    "библиотека музей центр студия лофт площадка магазин книжный зал "
    "концертный культурный творческое творческий дк".split()
)

_ENDINGS = sorted(
    "ого его ому ему ыми ими ой ей ий ый ая яя ое ее ые ие ую юю ом ем ах ях "
    "ам ям ов ев а я ы и у ю е о й ь".split(),
    key=len,
    reverse=True,
)


def normalize(text: str | None) -> str:
    """Lowercase, ё→е, punctuation and quotes → single spaces."""
    text = (text or "").lower().replace("ё", "е")
    return " ".join(_NON_WORD_RE.sub(" ", text).split())


def stem(word: str) -> str:
    """Crude Russian stem: doubled letters collapsed, one ending dropped."""
    word = _DOUBLE_RE.sub(r"\1", word)
    for end in _ENDINGS:
        if word.endswith(end) and len(word) - len(end) >= 3:
            return word[: -len(end)]
    return word


def _contains(text: str, phrase: str) -> bool:
    """``phrase`` starts at a word boundary of ``text`` (both normalized)."""
    return f" {phrase}" in f" {text}"


def _strip_type_words(name: str) -> str:
    tokens = name.split()
    while tokens and tokens[0] in _VENUE_TYPE_WORDS:
        tokens = tokens[1:]
    return " ".join(tokens)


def name_aliases(place_name: str | None) -> list[tuple[str, bool]]:
    """(normalized alias, is_bare): full name, then without leading type words."""
    name = normalize(_PAREN_RE.sub(" ", place_name or ""))
    aliases = [(name, False)] if len(name) >= MIN_ALIAS_LENGTH else []
    bare = _strip_type_words(name)
    if bare != name and len(bare) >= MIN_ALIAS_LENGTH:
        aliases.append((bare, True))
    return aliases


def venue_part(address: str | None) -> str:
    """The venue name an address usually starts with, type words dropped."""
    head = re.split(r"[,\n]", address or "", maxsplit=1)[0]
    return _strip_type_words(normalize(_PAREN_RE.sub(" ", head)))


def name_stems(text: str | None) -> set[str]:
    """Meaningful word stems of a venue name, type words excluded."""
    return {
        stem(t)
        for t in normalize(text).split()
        if len(t) >= 4
        and not t.isdigit()
        and t not in _VENUE_TYPE_WORDS
        and t not in _ADDRESS_NOISE
    }


@dataclass(frozen=True)
class AddressPoint:
    street: str
    house: int
    extra: str | None
    # Normalized text before the street — usually the venue name.
    prefix: str
    island: str | None = None  # во / пс


def _island(text: str) -> str | None:
    for code, pattern in _ISLAND_RES:
        if pattern.search(text):
            return code
    return None


def _street_key(tokens: list[str], j: int) -> str:
    word = "линия" if tokens[j] == "лин" else tokens[j]
    key = stem(word)
    k = j - 1
    while k >= 0 and tokens[k] in _ORDINAL_SUFFIXES:
        k -= 1
    if k < 0:
        return key
    prev = tokens[k]
    if prev.isdigit() and (word == "линия" or k < j - 1):
        return f"{prev} {key}"
    if word == "линия" and prev.isalpha() and prev not in _ADDRESS_NOISE:
        return f"{stem(prev)} {key}"
    if stem(prev) in _STREET_MODIFIERS:
        return f"{stem(prev)} {key}"
    return key


def parse_address(text: str | None) -> list[AddressPoint]:
    """Every (street, house) pair in a free-form address.

    «наб.р.Фонтанка 101», «наб Фонтанки 101» and «фонтанка 101» all give
    (фонтанк, 101); «ул. Передовиков, 16к2» gives (передовик, 16, к2).
    """
    tokens = _DIGIT_LETTER_RE.sub(" ", normalize(text)).split()
    island = _island(text or "")
    points = []
    for i, tok in enumerate(tokens):
        if not tok.isdigit():
            continue
        j = i - 1
        while j >= 0 and tokens[j] in _ADDRESS_NOISE:
            j -= 1
        if j < 0 or not tokens[j].isalpha() or len(tokens[j]) < 3:
            continue
        street = _street_key(tokens, j)
        extra = None
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        if nxt in _CORPUS_WORDS and i + 2 < len(tokens) and tokens[i + 2].isdigit():
            extra = f"к{tokens[i + 2]}"
        elif len(nxt) == 1 and nxt.isalpha() and nxt not in "кдм":
            extra = nxt
        start = j - len(street.split()) + 1
        prefix = " ".join(tokens[:start])
        points.append(AddressPoint(street, int(tok), extra, prefix, island))
    return points


def _same_building(a: AddressPoint, b: AddressPoint) -> bool:
    if (a.street, a.house) != (b.street, b.house):
        return False
    # «1 линия, 10» without an island may be either one.
    if (a.island or b.island) and a.island != b.island:
        return False
    return a.extra is None or b.extra is None or a.extra == b.extra


@dataclass
class PlaceIndex:
    """Everything needed to match a venue, built once per batch."""

    # (lowercased keyword, place_id), longest first: the original matcher,
    # tried first so already-matched events keep their place.
    raw_keywords: list = field(default_factory=list)
    # (normalized phrase, place_id), longest first.
    keywords: list = field(default_factory=list)
    aliases: list = field(default_factory=list)  # (alias, is_bare, place_id)
    addresses: list = field(default_factory=list)  # (AddressPoint, place_id)
    points: dict = field(default_factory=dict)  # place_id -> [AddressPoint]
    names: dict = field(default_factory=dict)  # place_id -> name stems
    roots: dict = field(default_factory=dict)  # place_id -> hub id

    @classmethod
    def build(cls, places, keywords) -> "PlaceIndex":
        """``places``: (id, name, address, main_place_id); ``keywords``: (kw, id)."""
        index = cls()
        keywords = [
            (kw, pid) for kw, pid in keywords if len(kw or "") >= MIN_KEYWORD_LENGTH
        ]
        index.raw_keywords = sorted(
            ((kw.lower(), pid) for kw, pid in keywords), key=lambda k: -len(k[0])
        )
        kws = {(normalize(kw), pid) for kw, pid in keywords}
        index.keywords = sorted((k for k in kws if k[0]), key=lambda k: -len(k[0]))
        aliases = set()
        for pid, name, address, main_place_id in places:
            aliases.update((alias, bare, pid) for alias, bare in name_aliases(name))
            index.points[pid] = parse_address(address)
            index.addresses.extend((p, pid) for p in index.points[pid])
            index.names[pid] = name_stems(name) | {
                s for kw, kpid in index.keywords if kpid == pid for s in name_stems(kw)
            }
            index.roots[pid] = main_place_id or pid
        index.aliases = sorted(aliases, key=lambda a: (-len(a[0]), a[1]))
        return index

    def match(self, address: str | None, title: str | None = None):
        """Place id for an event, or None when nothing fits unambiguously."""
        return self.explain(address, title)[0]

    def explain(self, address: str | None, title: str | None = None):
        """(place_id, how) — how is keyword / name / address / None."""
        raw = " ".join(filter(None, (address, title)))
        lowered = raw.lower()
        for kw, pid in self.raw_keywords:
            if kw in lowered:
                return pid, "keyword"
        text = normalize(raw)
        for kw, pid in self.keywords:
            if _contains(text, kw):
                return pid, "keyword"
        addr = normalize(address)
        if not addr:
            return None, None
        pid = self._match_name(address, addr)
        if pid:
            return pid, "name"
        pid = self._match_address(address)
        return (pid, "address") if pid else (None, None)

    def _match_name(self, address: str, addr: str):
        points = parse_address(address)
        venue = None
        for alias, bare, pid in self.aliases:
            if not _contains(addr, alias):
                continue
            known = self.points.get(pid) or []
            if points and known:
                # Same name, different building: a namesake, not this venue.
                if not any(_same_building(a, b) for a in points for b in known):
                    continue
            elif bare:
                # A bare alias is often an ordinary word («мастерская»,
                # «особняк»); without an address it must be the whole name.
                venue = venue_part(address) if venue is None else venue
                if venue != alias:
                    continue
            return pid
        return None

    def _match_address(self, address: str | None):
        hits = {}
        for point in parse_address(address):
            for known, pid in self.addresses:
                if _same_building(point, known):
                    hits[pid] = point
        if not hits:
            return None
        roots = {self.roots.get(pid, pid) for pid in hits}
        if len(roots) > 1:
            return None
        root = roots.pop()
        pid = root if root in hits or len(hits) > 1 else next(iter(hits))
        # The building alone is not enough — a new venue may have opened
        # there. The event must also name the place in some other spelling.
        names = self.names.get(pid, set())
        if not any(name_stems(point.prefix) & names for point in hits.values()):
            return None
        return pid
