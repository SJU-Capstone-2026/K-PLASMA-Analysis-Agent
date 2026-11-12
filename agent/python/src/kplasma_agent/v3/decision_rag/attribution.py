"""Conservative query scope and citation roles, separate from stored ownership.

This layer only reads text. A saved note cannot grant retrieval permission or
change the record policy, and annotations never replace source metadata.
"""
from __future__ import annotations

from copy import deepcopy
import re


_REFERENCE = r"비교|참조|인용|(?:다른|옆|앞|이전|상대|타)\s*(?:후보|안|run)"
_SHARED = (r"(?:공통|공동|묶음|전체)\s*(?:메모|기록|코멘트|평|소감|의견|판단)|"
           r"(?:개별\s*)?귀속|(?:누구|어느\s*후보)[^.!?\n]{0,24}(?:메모|기록|의견|판단|코멘트)|"
           r"(?:메모|기록|의견|판단|코멘트)[^.!?\n]{0,24}(?:누구|어느\s*후보)|공통으로\s*(?:남긴|적은|작성)")
_GROUP_QUERY = (r"공통|공동|묶음|후보군|후보\s*묶음|(?:두|여러|전체)\s*후보[^.!?\n]{0,20}전체|"
                r"특정\s*후보[^.!?\n]{0,16}붙이지|누구[^.!?\n]{0,20}(?:귀속|해당|사유)|종합\s*의견")
_NEGATIVE = (r"말아|"
             r"빼(?:고|줘|주세요|라|서)|제외(?:해|하|시켜|\s*$)|"
             r"(?:채우|섞|넓히|쓰|보여주|포함하|끌어오|가져오|언급하|인용하|참조하|비교하|사용하|이야기하|찾|검색하|읽|반환하)지|"
             r"(?:안|못)\s*(?:보여|찾|포함|참조|인용|비교|사용|읽)|"
             r"(?:비교|참조|인용|(?:공통|공동)\s*(?:메모|기록|코멘트|평가|의견|판단)|다른\s*후보)[은는을를]?\s*말고|"
             r"필요\s*(?:없|하지\s*않)|원하지|금지|배제")
_ATTRIBUTION_BAN = re.compile(
    r"(?:(?:추측|추정|단정|확정|배정|할당|지정|귀속|판단|간주|해석)(?:하|시키)|붙이|돌리|옮기)지\s*"
    r"(?:말(?:아|고|라)?(?:줘|주세요)?|마(?:세요|라)?)"
)
_READ_ACTION = re.compile(r"찾|검색|보여|읽|가져오|포함|참조|인용|정리|구분|분리|대조|알려|살펴")
_INDIVIDUAL = r"후보별|개별|자체|자신|단독|각\s*후보"
_NOTE = r"메모|기록|코멘트|의견|판단"
_JOINT_REVIEW = re.compile(
    r"(?:함께|같이|동시에)[^.!?;]{0,20}(?:검토|논의|평가|심사)|"
    r"(?:공동|같은|동일)[^.!?;]{0,10}(?:검토|논의|평가|심사|회의)|"
    r"(?:같은|동일|하나의|한)\s*(?:후보\s*)?(?:묶음|후보군|그룹)", re.I)
_ANY_GROUP_MEMBER = re.compile(
    r"(?:후보|run|실험)(?:들|군)?\s*(?:중|가운데)[^.!?;]{0,8}(?:하나|한\s*후보|일부)|"
    r"하나라도\s*(?:포함|연결|겹)|(?:일부|하나)만\s*(?:포함|연결|겹)", re.I)
_FOREIGN_SUBJECT = re.compile(
    r"(?:앞서|이전에|앞에서|지난번에?)\s*(?:검토|비교|살펴|보았|봤|선택|논의)[^.!?\n]{0,16}(?:안|후보)|"
    r"(?:다른|옆|앞선|이전|앞|상대|타)\s*(?:후보|안)(?!전)|"
    r"(?:그|저)\s*(?:후보|안)(?:은|는|이|가|의|에)|"
    r"(?:누구|어느\s*후보|어떤\s*후보)[^.!?\n]{0,24}(?:불명|모르|명시[^.!?\n]{0,8}않|확실[^.!?\n]{0,8}않)",
    re.IGNORECASE,
)
_SHARED_SUBJECT = re.compile(
    r"(?:두|세|모든|전체)\s*(?:후보|안)|후보들(?:은|이|의|\s*모두)|"
    r"(?:공통|공동|묶음)\s*(?:메모|의견|평가|소감)|전체적으로|전반적으로"
)


def _mentions(text, identifier):
    # ASCII boundaries also work when an identifier is followed by a Korean particle.
    return bool(re.search(r"(?<![A-Za-z0-9_-])" + re.escape(identifier) + r"(?![A-Za-z0-9_-])", text, re.I))


def _command_text(question, known_ids):
    # Quoted note content is not a request to widen scope. Scope commands are
    # evaluated only in the question, never in the saved document text.
    def quoted(match):
        inner = match[0][1:-1].strip()
        return inner if any(inner.casefold() == identifier.casefold() for identifier in known_ids) else ""

    return re.sub(r'"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|\x27[^\x27\n]*\x27|`[^`\n]*`', quoted, question)


def _permission_clauses(command):
    # Coordinated commands may have different subjects: "show shared notes,
    # do not include another Run". Keep a ban on its own requested action.
    command = re.sub(r"((?:찾|보여주|가져오|읽|포함하|참조하|인용하|정리하)(?:고|되))\s*", r"\1;", command)
    command = re.sub(
        r"((?:찾아|보여|알려|가져와|읽어|정리해)(?:줘|주세요|주라)?)\s*[,，]", r"\1;", command)
    # A comma after the object ("shared notes, do not read them") must not
    # detach that object from its prohibition and accidentally grant access.
    return re.split(r"[.!?;\n]|하지만|다만|(?<=말고)", command)


def _permissions(question, known_ids, selected_ids=()):
    command = _command_text(question, known_ids)
    focal_subject = (r"(?:이|해당|현재|선택한|선택된|본|자기)\s*(?:후보|run|안)|"
                     r"(?<![A-Za-z0-9_-])(?:RUN|SYN|R)[-_][A-Za-z0-9_-]+")
    self_only = bool(re.search(
        r"(?:" + focal_subject + r")(?:(?!비교|참조|인용|공통|공동|묶음|여러|누구|귀속)[^.!?\n]){0,30}"
        r"(?:만|자체|단독|개별)", command, re.I))
    explicit_foreign = {identifier for identifier in known_ids if _mentions(command, identifier)} - set(selected_ids)
    if self_only and not explicit_foreign:
        return False, False
    references = shared = False
    reference_blocked = shared_blocked = False
    for clause in _permission_clauses(command):
        # "Do not guess its owner" constrains interpretation after retrieval;
        # it neither prohibits reading the note nor independently grants access.
        clause, attribution_bans = _ATTRIBUTION_BAN.subn("", clause)
        has_reference = bool(re.search(_REFERENCE, clause, re.I))
        has_shared = bool(re.search(_SHARED + "|" + _GROUP_QUERY, clause, re.I))
        # A negated ban is not itself an affirmative request. An explicit
        # positive request after it can still grant permission (e.g. 빼지 말고 비교해줘).
        without_negated_ban = re.sub(r"(?:빼|제외하|배제하)지\s*말고", "", clause)
        negative = bool(re.search(_NEGATIVE, without_negated_ban))
        reference_blocked |= has_reference and negative
        shared_blocked |= has_shared and negative
        if negative:
            continue
        if attribution_bans and not _READ_ACTION.search(clause):
            continue
        # Comparing counts, conditions, or other scalar fields does not ask to
        # retrieve another candidate's notes. Require a contextual-note subject
        # or an explicit comparison of at least two named Runs.
        reference_subject = bool(re.search(
            r"비교에만|참조(?:한|했던|로만|에만|되)|인용(?:한|했던)|"
            r"비교\s*(?:메모|기록|근거|문장|참조|이력|내용|자료|사유|사례|코멘트|대상|기준)|"
            r"비교(?:에서|했던|한|하던|할\s*때|\s*당시)[^.!?\n]{0,16}(?:메모|기록|근거|문장)|"
            r"(?:다른|옆|앞|이전|상대|타|두|세|각|여러)\s*(?:후보|안|run)", clause, re.I))
        named_comparison = (len({identifier.casefold() for identifier in known_ids if _mentions(clause, identifier)}) > 1
                            and "비교" in clause)
        references |= (reference_subject or named_comparison or bool(explicit_foreign)) and bool(re.search(
            r"비교(?!하지|할\s*필요)|참조(?!하지)|인용(?!하지)|"
            r"(?:다른|옆|앞|이전|상대|타)\s*(?:후보|안|run)[^.!?\n]{0,48}"
            r"(?:보여|찾|포함|알려|정리|살펴|읽어|사용)|"
            r"(?:보여|찾|알려|정리)", without_negated_ban, re.I))
        shared |= has_shared
    return references and not reference_blocked, shared and not shared_blocked


def _individual_only(command, shared):
    requested = []
    for clause in _permission_clauses(command):
        cleaned, attribution_bans = _ATTRIBUTION_BAN.subn("", clause)
        if not attribution_bans or _READ_ACTION.search(cleaned):
            requested.append(cleaned)
    command = ". ".join(requested)
    individual = bool(re.search(_INDIVIDUAL, command))
    if shared and _both_note_types(command):
        return False
    if re.search(r"개별[^.!?\n]{0,16}(?:아닌|아니라|말고|함께)|특정\s*후보[^.!?\n]{0,16}붙이지", command):
        return False
    if shared and re.search(
            r"(?:" + _INDIVIDUAL + r")[^.!?\n]{0,28}(?:구분|분리|대조)|"
            r"(?:구분|분리|대조)[^.!?\n]{0,28}(?:" + _INDIVIDUAL + r")", command):
        return False
    if re.search(_GROUP_QUERY, command) and re.search(
            r"개별[^.!?\n]{0,24}(?:명시되지|명시하지|불명|(?:귀속|배정|할당|지정)[^.!?\n]{0,12}(?:않|말|하지))", command):
        return False
    return individual


def _both_note_types(command):
    # Distinguishing two requested types is different from asking only for
    # shared notes and warning against individual attribution.
    shared_note = r"(?:공동|공통|묶음)\s*(?:" + _NOTE + r")"
    individual_note = r"(?:" + _INDIVIDUAL + r")\s*(?:후보(?:의)?\s*)?(?:" + _NOTE + r")"
    return bool(re.search(
        r"(?:" + shared_note + r"\s*(?:와|과|및)(?:\s*함께)?\s*" + individual_note + r"|"
        + individual_note + r"\s*(?:와|과|및)(?:\s*함께)?\s*" + shared_note + r")", command))


def _shared_cohort(command, known_ids, selected_ids):
    """Require co-review membership only when the request names that relation.

    Attachment scope remains an ANY relationship by default. A large search
    inventory does not imply that every attached Run belongs to one review.
    """
    positive = []
    for clause in _permission_clauses(command):
        cleaned, bans = _ATTRIBUTION_BAN.subn("", clause)
        if re.search(_NEGATIVE, cleaned) or (bans and not _READ_ACTION.search(cleaned)):
            continue
        positive.append(cleaned)
    requested = ". ".join(positive)
    if _ANY_GROUP_MEMBER.search(requested):
        return set()
    joint = bool(_JOINT_REVIEW.search(requested))
    named = {identifier for identifier in known_ids if _mentions(requested, identifier)}
    if named:
        # Explicit focal names define the requested subset, even when the
        # caller attached a much larger searchable inventory.
        return named
    if not joint:
        return set()
    if re.search(
            r"(?:첨부(?:한|된)?|선택(?:한|된)?|붙인|해당|이)\s*"
            r"(?:(?:모든|전체)\s*(?:후보|run|실험)|(?:후보|run|실험)(?:들|군|\s*묶음))", requested, re.I):
        return set(selected_ids)
    # A count explicitly identifies the whole selected co-review group only
    # when it agrees with that selection; 'two Runs' in a 150-Run inventory
    # cannot silently turn into an all-150 requirement.
    counts = {"두": 2, "둘": 2, "세": 3, "셋": 3, "네": 4, "넷": 4}
    for match in re.finditer(r"(?<![가-힣0-9])(두|둘|세|셋|네|넷|[0-9]+)\s*(?:개(?:의)?\s*)?(?:후보|run|실험)", requested, re.I):
        word = match[1]
        count = counts[word] if word in counts else int(word)
        if count >= 2 and count == len(selected_ids):
            return set(selected_ids)
    return set()


def _shared_members(document):
    refs = document.get("candidateRunRefs")
    if isinstance(refs, list):
        return {ref["runId"] for ref in refs if isinstance(ref, dict) and isinstance(ref.get("runId"), str)}
    return set(document.get("referencedRunIds", []))


def _known_ids(documents):
    return {identifier for document in documents
            for identifier in [document.get("runId"), *document.get("referencedRunIds", []),
                               *document.get("matchedRunIds", [])]
            if isinstance(identifier, str) and identifier}


def _citation_role(document, known_ids):
    if document["attribution"] == "SHARED_UNASSIGNED":
        return "SHARED_UNASSIGNED"
    if document.get("scopeRole") == "REFERENCE_ONLY":
        return "REFERENCE_ONLY"
    text, owner = document.get("text", ""), document.get("runId")
    if _FOREIGN_SUBJECT.search(text):
        return "REFERENCE_ONLY"
    if _SHARED_SUBJECT.search(text):
        # Only an actual overallComment source has the shared role. Collective
        # prose saved in an individual note does not change its source type.
        return "REFERENCE_ONLY"
    labels = re.findall(r"(?:후보|안)\s*([A-Z]|[0-9]{1,3})(?![A-Za-z0-9_-])|"
                        r"(?<![A-Za-z0-9_-])([A-Z]|[0-9]{1,3})\s*(?:후보|안)", text)
    if any((before or after).casefold() != str(owner).casefold() for before, after in labels):
        return "REFERENCE_ONLY"
    mentioned = {identifier for identifier in known_ids if _mentions(text, identifier)}
    # Unknown but recognisable Run IDs are also not evidence about the owner.
    mentioned.update(re.findall(r"(?<![A-Za-z0-9_-])(?:RUN|SYN|R)[-_][A-Za-z0-9_-]+", text, re.I))
    foreign = {identifier for identifier in mentioned if identifier.casefold() != str(owner).casefold()}
    if foreign:
        def subject(identifier):
            return bool(re.search(re.escape(identifier) + r"\s*(?:후보|안|run)?\s*(?:은|는|이|가|의)", text, re.I))
        if not owner or not subject(owner) or any(subject(identifier) for identifier in foreign):
            return "REFERENCE_ONLY"
    return "PER_RUN"


def annotate_documents(scoped_docs):
    """Copy documents and describe prose attribution without filtering records."""
    documents = list(scoped_docs)
    known_ids = _known_ids(documents)
    return [{**deepcopy(document), "citationRole": _citation_role(document, known_ids)}
            for document in documents]


def select_documents(question, scoped_docs, *, selected_run_ids=None):
    """Select semantic evidence; never expand the caller's version/Run scope.

    Uncertain or foreign-subject prose is contextual evidence only. Permission
    must be affirmative, and a prohibition takes precedence over broad keywords.
    """
    documents = annotate_documents(scoped_docs)
    if selected_run_ids is None:
        selected_ids = {identifier for document in documents for identifier in document.get("matchedRunIds", [])}
        if not selected_ids:
            selected_ids = {document["runId"] for document in documents if document.get("scopeRole") == "SUBJECT"}
    else:
        # The caller's validated selection includes Runs with no saved notes.
        # Inferring it from document presence would silently shrink a cohort.
        selected_ids = set(selected_run_ids)
        if not selected_ids:
            return []
    known_ids = _known_ids(documents) | selected_ids
    command = _command_text(question, known_ids)
    references, shared = _permissions(question, known_ids, selected_ids)
    individual_only = _individual_only(command, shared)
    if individual_only:
        shared = False
    shared_only = shared and bool(re.search(_GROUP_QUERY, command)) and not individual_only and not _both_note_types(command)
    shared_cohort = _shared_cohort(command, known_ids, selected_ids) if shared else set()
    mentioned_ids = {identifier for identifier in known_ids if _mentions(command, identifier)}
    requested_foreign_ids = mentioned_ids - selected_ids
    focal_ids = mentioned_ids or selected_ids
    ambiguous_focus = (len(selected_ids) > 1 and not mentioned_ids and bool(re.search(
        r"(?:이|그|해당|현재)\s*(?:후보|run|안)(?!들)|이것", command, re.I)))
    result = []
    for document in documents:
        role = document["citationRole"]
        if requested_foreign_ids and not (mentioned_ids & selected_ids) and document.get("runId") not in requested_foreign_ids and not any(
                _mentions(document.get("text", ""), identifier) for identifier in requested_foreign_ids):
            continue
        if shared_only and role != "SHARED_UNASSIGNED":
            continue
        if role == "PER_RUN" and (ambiguous_focus or document.get("runId") not in focal_ids):
            role = document["citationRole"] = "REFERENCE_ONLY"
        if role == "REFERENCE_ONLY" and not references:
            continue
        if role == "SHARED_UNASSIGNED" and not shared:
            continue
        if role == "SHARED_UNASSIGNED" and shared_cohort and not shared_cohort.issubset(_shared_members(document)):
            continue
        result.append(document)
    return result
